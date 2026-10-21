// Shared by the soldier's shaders (camo.gdshader, gear.gdshader, weapon.gdshader).
//
// The soldier's mesh carries two baked extras (art/soldier/build_soldier.py):
// - Each vertex's REST position in its two UV maps — UV = (x, z), UV2 = (y, 0) in
//   Blender's axes. Godot skins the mesh before the shader runs, so a pattern drawn at
//   VERTEX would slide over the cloth as he moves; drawn at the rest position it stays
//   printed on the fabric. `SOLDIER_VERTEX` decodes it into Godot's axes (y up).
// - Ambient occlusion in the vertex color (red): creases, the gaps between pouches and
//   the underside of the helmet see less sky.
//
// Detail finer than a pixel is faded out (`detail`), so the weave doesn't shimmer at
// the game's camera distance and only shows up close.

varying vec3 v_rest;
varying float v_ao;

#define SOLDIER_VERTEX v_rest = vec3(UV.x, 1.0 - UV.y, -UV2.x); v_ao = COLOR.r;

float hash(vec3 p) {
	p = fract(p * 0.3183099 + vec3(0.1, 0.2, 0.3));
	p *= 17.0;
	return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}

float noise(vec3 p) {
	vec3 i = floor(p);
	vec3 f = fract(p);
	f = f * f * (3.0 - 2.0 * f);
	return mix(
		mix(mix(hash(i), hash(i + vec3(1.0, 0.0, 0.0)), f.x),
			mix(hash(i + vec3(0.0, 1.0, 0.0)), hash(i + vec3(1.0, 1.0, 0.0)), f.x), f.y),
		mix(mix(hash(i + vec3(0.0, 0.0, 1.0)), hash(i + vec3(1.0, 0.0, 1.0)), f.x),
			mix(hash(i + vec3(0.0, 1.0, 1.0)), hash(i + vec3(1.0, 1.0, 1.0)), f.x), f.y),
		f.z);
}

float fbm(vec3 p) {
	return noise(p) * 0.5 + noise(p * 2.03 + 3.1) * 0.3 + noise(p * 4.07 + 7.7) * 0.2;
}

// 1 where a feature `period` meters across is several pixels wide, 0 where it is sub-pixel.
float detail(float period, float pixel) {
	return smoothstep(0.5 * period, 0.12 * period, pixel);
}

// Cloth texture as a height in meters: a fine, slightly stretched noise at the thread
// scale (a printed sine weave on a curved surface shows contour rings instead).
float weave(vec3 p, float period) {
	vec3 q = p / period;
	return (noise(q * vec3(1.0, 2.2, 1.0)) * 0.6 + noise(q * vec3(2.3, 1.0, 2.3) + 9.1) * 0.4 - 0.5) * period * 0.35;
}

// Bump mapping without tangents (Mikkelsen's surface gradient): perturbs view-space
// normal `n` by a height field, given the screen derivatives of the position and height.
vec3 bump(vec3 n, vec3 dpdx, vec3 dpdy, float dhdx, float dhdy) {
	vec3 r1 = cross(dpdy, n);
	vec3 r2 = cross(n, dpdx);
	float det = dot(dpdx, r1);
	vec3 grad = sign(det) * (dhdx * r1 + dhdy * r2);
	return normalize(abs(det) * n - grad);
}
