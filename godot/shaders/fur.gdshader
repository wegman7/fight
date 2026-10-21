// The pug's short black coat (its `Fur` material, swapped in by godot/models/pug.glb.import).
//
// art/pug/build_pug.py (`rest_uvs`) bakes two things into the fur's UVs: UV = the
// rest position's (x, z) and UV2 = (rest y, shade), Blender axes (x forward, y the
// dog's left, z up), glTF flipping each V. Laying the hair out in rest space keeps it
// fixed to the skin however the bones move. `shade` is 1 in the open and drops in the
// wrinkles, under the ears and between the legs (ambient occlusion baked at rest,
// deepened in the sculpted creases).
//
// Fur, not skin: a soft wrapped diffuse, a highlight stretched across the hairs
// (Kajiya-Kay, along the way the coat lies: back from the nose, down the flanks and
// legs), and a velvety sheen toward the silhouette. Up close, single strands break the
// highlight up; they fade out once a pixel covers more than a hair's width, so at the
// game's camera distance nothing shimmers.
shader_type spatial;

uniform vec3 color : source_color = vec3(0.036, 0.032, 0.03);
// Hair tips catch a little brown in the light.
uniform vec3 tip_color : source_color = vec3(0.075, 0.062, 0.052);
// The velvety sheen of the hairs toward the silhouette.
uniform vec3 sheen_color : source_color = vec3(0.3, 0.28, 0.27);
uniform float sheen : hint_range(0.0, 2.0) = 0.45;
// The highlight along the hairs: its strength and how tight it is.
uniform float gloss : hint_range(0.0, 1.0) = 0.045;
uniform float gloss_power = 18.0;
// How far light wraps past the terminator (scattering through the coat).
uniform float wrap : hint_range(0.0, 1.0) = 0.35;
// How strongly single strands show up close.
uniform float strand_contrast : hint_range(0.0, 2.0) = 0.7;
// How dark the deepest creases get.
uniform float crease_dark : hint_range(0.0, 1.0) = 0.75;

varying vec3 rest;
varying float shade;
varying vec3 hair;  // view space, along the hairs
varying float strand;
varying float combed;  // 1 where the hair lies along the skin, 0 where it points into it

void vertex() {
	rest = vec3(UV.x, UV2.x, 1.0 - UV.y);
	shade = 1.0 - UV2.y;
}

float hash(vec3 p) {
	p = fract(p * 0.3183099 + vec3(0.71, 0.113, 0.419));
	p *= 17.0;
	return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}

float noise(vec3 x) {
	vec3 i = floor(x);
	vec3 f = fract(x);
	f = f * f * (3.0 - 2.0 * f);
	return mix(
		mix(mix(hash(i), hash(i + vec3(1, 0, 0)), f.x), mix(hash(i + vec3(0, 1, 0)), hash(i + vec3(1, 1, 0)), f.x), f.y),
		mix(mix(hash(i + vec3(0, 0, 1)), hash(i + vec3(1, 0, 1)), f.x), mix(hash(i + vec3(0, 1, 1)), hash(i + vec3(1, 1, 1)), f.x), f.y),
		f.z);
}

// The way the hair lies at rest position p: back toward the tail, sloping down the
// flanks, and straight down the legs below the belly.
vec3 flow(vec3 p) {
	vec3 body = normalize(vec3(-1.0, 0.0, -0.2 - 2.5 * abs(p.y)));
	float leg = smoothstep(0.3, 0.2, p.z);
	return normalize(mix(body, vec3(0.15, 0.0, -1.0), leg));
}

// Hairs about `period` m apart lying along f, each `stretch` times longer than wide:
// two skewed layers multiplied, so single strands stand out instead of a grain.
float strands(vec3 p, vec3 f, float period, float stretch) {
	vec3 side = normalize(cross(f, vec3(0.0, 1.0, 0.0)));
	vec3 up = cross(side, f);
	vec3 q = vec3(dot(p, f) / stretch, dot(p, side), dot(p, up)) / period;
	float a = noise(q);
	float b = noise(vec3(q.x * 1.3 + q.y * 0.21, q.y * 1.7 - q.z * 0.37, q.z * 1.7 + q.y * 0.37) + 19.1);
	return clamp(a * b * 2.2, 0.0, 1.0);
}

void fragment() {
	vec3 f = flow(rest);
	vec3 drx = dFdx(rest);
	vec3 dry = dFdy(rest);
	vec3 dvx = dFdx(VERTEX);
	vec3 dvy = dFdy(VERTEX);

	// Rest-space meters per pixel: hide what a pixel can't resolve.
	float px = length(abs(drx) + abs(dry));
	float fine = 1.0 - smoothstep(0.0006, 0.002, px);
	float clump = 1.0 - smoothstep(0.0015, 0.005, px);
	float h = ((strands(rest, f, 0.0016, 7.0) - 0.45) * fine
		+ (strands(rest + vec3(3.1, 7.7, 1.3), f, 0.006, 4.0) - 0.45) * clump * 0.6) * strand_contrast;
	strand = h;

	// The hair direction on screen: write f in terms of the two screen steps in rest
	// space, then take the same steps in view space.
	float a = dot(drx, drx), b = dot(drx, dry), c = dot(dry, dry);
	float det = a * c - b * b;
	vec3 t = vec3(0.0, 1.0, 0.0);
	combed = 0.0;
	if (det > 1e-20) {
		float u = dot(drx, f), v = dot(dry, f);
		float ku = (c * u - b * v) / det, kv = (a * v - b * u) / det;
		t = dvx * ku + dvy * kv;
		combed = smoothstep(0.25, 0.6, length(drx * ku + dry * kv));
	}
	// That direction is worked out per triangle, so it steps across tight creases:
	// there, fall back to a plain highlight.
	combed *= smoothstep(0.55, 0.9, shade);
	t -= NORMAL * dot(NORMAL, t);
	// Each strand tilts a little, so the highlight breaks into hairs.
	hair = normalize(t + 1e-6) + NORMAL * (h * 0.35 - 0.06);

	ALBEDO = mix(color, tip_color, clamp(0.35 + h * 1.4, 0.0, 1.0) * 0.55) * mix(1.0 - crease_dark, 1.0, shade);
	ROUGHNESS = 0.6;
	SPECULAR = 0.25;  // the sky's reflection, blurred
	AO = shade;
	AO_LIGHT_AFFECT = 0.3;
}

void light() {
	float ndl = dot(NORMAL, LIGHT);
	vec3 lit = LIGHT_COLOR * ATTENUATION / PI;
	DIFFUSE_LIGHT += lit * clamp((ndl + wrap) / (1.0 + wrap), 0.0, 1.0);

	// Kajiya-Kay: brightest where the half vector is square to the hairs. Where the
	// hair points out of the skin there is no "along": a plain lobe instead.
	vec3 hv = normalize(LIGHT + VIEW);
	float s = sqrt(max(0.0, 1.0 - pow(dot(normalize(hair), hv), 2.0)));
	s = mix(clamp(dot(NORMAL, hv), 0.0, 1.0), s, combed);
	float facing = smoothstep(-0.1, 0.4, ndl);
	SPECULAR_LIGHT += lit * PI * gloss * pow(s, gloss_power) * facing * (0.85 + strand * 0.6) * shade;

	// Sheen: fine hairs catching the light toward the silhouette.
	float rim = pow(1.0 - clamp(dot(NORMAL, VIEW), 0.0, 1.0), 3.0);
	SPECULAR_LIGHT += lit * sheen_color * sheen * rim * clamp(ndl + 0.5, 0.0, 1.0) * shade;
}
