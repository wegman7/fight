// The soldier's fatigues (its `Camo` material, swapped in by
// godot/models/soldier.glb.import). A procedural woodland camo in object space, so it
// needs no UVs: soft olive, brown and tan blobs over a dark green base.
shader_type spatial;

uniform vec3 base_color : source_color = vec3(0.30, 0.36, 0.20);
uniform vec3 olive_color : source_color = vec3(0.40, 0.45, 0.26);
uniform vec3 brown_color : source_color = vec3(0.38, 0.30, 0.20);
uniform vec3 tan_color : source_color = vec3(0.55, 0.52, 0.36);
uniform float scale : hint_range(1.0, 40.0) = 9.0;
uniform float roughness : hint_range(0.0, 1.0) = 0.9;

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
	vec3 p = v_pos * scale;
	// Two octaves of blobby noise, pinched into soft irregular patches.
	float n = noise(p) * 0.62 + noise(p * 2.1 + 7.3) * 0.38;
	n = smoothstep(0.25, 0.75, n);
	vec3 camo = mix(base_color, olive_color, step(0.45, n));
	camo = mix(camo, brown_color, smoothstep(0.55, 0.75, n));
	camo = mix(camo, tan_color, smoothstep(0.85, 0.98, n));
	ALBEDO = camo;
	ROUGHNESS = roughness;
	SPECULAR = 0.2;
}
