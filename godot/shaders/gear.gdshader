// The soldier's gear (its `Vest`, `VestPouch`, `Balaclava` and `Boot` materials, swapped
// in by godot/models/soldier.glb.import): one worn-fabric-and-leather shader in object
// space, so it needs no UVs. Sun-faded blotches, a grain in the normal and dirt
// gathered low on the body — the colors come from each material's `.tres`.
//
// The noise helpers are copied from `camo.gdshader` (the fatigues), which shades the
// same way in camo colors.
shader_type spatial;
render_mode diffuse_burley, specular_schlick_ggx;

uniform vec3 color : source_color = vec3(0.40, 0.36, 0.26);
uniform vec3 dirt_color : source_color = vec3(0.13, 0.12, 0.09);
uniform float roughness : hint_range(0.0, 1.0) = 0.93;
uniform float specular : hint_range(0.0, 1.0) = 0.22;
uniform float grime : hint_range(0.0, 1.0) = 0.35;
uniform float variation : hint_range(0.0, 1.0) = 0.28;
uniform float grain : hint_range(0.0, 1.0) = 0.3;
uniform float grain_scale : hint_range(40.0, 400.0) = 230.0;

varying vec3 v_pos;

float hash(vec3 p) {
	p = fract(p * 0.3183099 + vec3(0.1, 0.2, 0.3));
	p *= 17.0;
	return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}

float noise(vec3 p) {
	vec3 i = floor(p);
	vec3 f = fract(p);
	f = f * f * (3.0 - 2.0 * f);
	float n000 = hash(i);
	float n100 = hash(i + vec3(1.0, 0.0, 0.0));
	float n010 = hash(i + vec3(0.0, 1.0, 0.0));
	float n110 = hash(i + vec3(1.0, 1.0, 0.0));
	float n001 = hash(i + vec3(0.0, 0.0, 1.0));
	float n101 = hash(i + vec3(1.0, 0.0, 1.0));
	float n011 = hash(i + vec3(0.0, 1.0, 1.0));
	float n111 = hash(i + vec3(1.0, 1.0, 1.0));
	return mix(
		mix(mix(n000, n100, f.x), mix(n010, n110, f.x), f.y),
		mix(mix(n001, n101, f.x), mix(n011, n111, f.x), f.y),
		f.z);
}

void vertex() {
	v_pos = VERTEX;
}

void fragment() {
	// Fading: coarse blotches lifting the color where the gear wears and sun-bleaches.
	float fade = noise(v_pos * 7.0) * 0.6 + noise(v_pos * 17.0 + 5.3) * 0.4;
	vec3 albedo = mix(color, color * 1.3 + vec3(0.02), fade * variation);
	// Dirt: gathered low on the body, with a few splashes further up.
	float low = smoothstep(0.6, 0.03, v_pos.y);
	float splashes = smoothstep(0.42, 0.86, noise(v_pos * 9.0 + 31.0));
	albedo = mix(albedo, dirt_color, clamp(grime * (low * 0.7 + splashes * 0.4), 0.0, 0.8));

	// Grain: crossed ripples in the normal, and a rougher finish over the dirt.
	vec3 wobble = vec3(sin(v_pos.x * grain_scale) * sin(v_pos.z * grain_scale * 0.92),
	                   sin(v_pos.y * grain_scale) * sin(v_pos.x * grain_scale * 0.96), 0.0);
	ALBEDO = albedo;
	ROUGHNESS = clamp(mix(roughness, roughness * 0.8, splashes) + (albedo.r - color.r) * 0.2, 0.0, 1.0);
	SPECULAR = specular;
	NORMAL = normalize(NORMAL + wobble * grain * 0.08);
}
