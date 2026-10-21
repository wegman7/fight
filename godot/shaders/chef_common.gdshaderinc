// Shared by the chef's shaders (chef_*.gdshader). His mesh carries, per vertex (see
// `surface_data` in art/fighter/build_fighter.py):
//   UV = (rest x, rest z), UV2.x = rest y: the rest-pose position in Blender axes
//        (x forward, y his left, z up, meters), so patterns stay glued to the skin
//        and cloth while the skeleton deforms the mesh. glTF flips V on export.
//   COLOR.r = ambient occlusion baked in the rest pose; COLOR.g / COLOR.b = masks
//        whose meaning depends on the material.

vec3 rest_position(vec2 uv, vec2 uv2) {
	return vec3(uv.x, uv2.x, 1.0 - uv.y);
}

float chef_hash(vec3 p) {
	p = fract(p * 0.3183099 + vec3(0.1, 0.2, 0.3));
	p *= 17.0;
	return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}

// Value noise in 0..1.
float chef_noise(vec3 p) {
	vec3 i = floor(p);
	vec3 f = fract(p);
	f = f * f * (3.0 - 2.0 * f);
	return mix(
		mix(mix(chef_hash(i), chef_hash(i + vec3(1, 0, 0)), f.x),
			mix(chef_hash(i + vec3(0, 1, 0)), chef_hash(i + vec3(1, 1, 0)), f.x), f.y),
		mix(mix(chef_hash(i + vec3(0, 0, 1)), chef_hash(i + vec3(1, 0, 1)), f.x),
			mix(chef_hash(i + vec3(0, 1, 1)), chef_hash(i + vec3(1, 1, 1)), f.x), f.y),
		f.z);
}

float chef_fbm(vec3 p) {
	return chef_noise(p) * 0.5 + chef_noise(p * 2.03 + 11.1) * 0.3 + chef_noise(p * 4.1 + 23.7) * 0.2;
}

// How much of a pattern with `freq` cycles per meter to keep, given `footprint`
// meters per pixel: fades detail out before it can alias into shimmer.
float detail_fade(float footprint, float freq) {
	return 1.0 - smoothstep(0.15, 0.45, footprint * freq);
}

// Bump mapping without tangents (Mikkelsen's surface gradient): perturbs view-space
// normal `n` at view-space `pos` by the height field `h` (meters).
vec3 bump_normal(vec3 n, vec3 pos, float h) {
	vec3 dpdx = dFdx(pos);
	vec3 dpdy = dFdy(pos);
	vec3 r1 = cross(dpdy, n);
	vec3 r2 = cross(n, dpdx);
	float det = dot(dpdx, r1);
	vec3 grad = sign(det) * (dFdx(h) * r1 + dFdy(h) * r2);
	return normalize(abs(det) * n - grad);
}
