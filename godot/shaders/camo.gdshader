// The soldier's fatigues (its `Camo` material, swapped in by
// godot/models/soldier.glb.import). A procedural woodland camo in object space, so it
// needs no UVs: soft olive, brown and tan blobs over a dark green base, with sun-faded
// blotches, a cloth grain and dirt gathered low on the body, so the fatigues read as
// worn fabric rather than plastic.
//
// The noise helpers are copied in `gear.gdshader` (the carrier, pouches, balaclava and
// boots), which shades the same way in its own colors.
shader_type spatial;
render_mode diffuse_burley, specular_schlick_ggx;

uniform vec3 base_color : source_color = vec3(0.20, 0.24, 0.14);
uniform vec3 olive_color : source_color = vec3(0.28, 0.32, 0.19);
uniform vec3 brown_color : source_color = vec3(0.26, 0.20, 0.13);
uniform vec3 tan_color : source_color = vec3(0.36, 0.34, 0.24);
uniform vec3 dirt_color : source_color = vec3(0.14, 0.13, 0.09);
uniform float scale : hint_range(1.0, 40.0) = 14.0;
uniform float roughness : hint_range(0.0, 1.0) = 0.95;
uniform float grime : hint_range(0.0, 1.0) = 0.45;
uniform float grain : hint_range(0.0, 1.0) = 0.3;

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
	// Three octaves of blobby noise, pinched into soft irregular patches: the coarse two
	// make the camo shapes, the third only breaks up their edges.
	float n = noise(p) * 0.55 + noise(p * 2.3 + 7.3) * 0.32 + noise(p * 5.1 + 1.7) * 0.13;
	float patch = smoothstep(0.28, 0.72, n);
	vec3 camo = mix(base_color, olive_color, step(0.44, patch));
	camo = mix(camo, brown_color, smoothstep(0.56, 0.74, patch));
	camo = mix(camo, tan_color, smoothstep(0.87, 0.98, patch));

	// Sun fade and dirt: blotchy, and heavier towards the boots.
	float fade = noise(v_pos * 6.0 + 21.0);
	camo = mix(camo, camo * 1.22, fade * 0.18);
	float low = smoothstep(0.62, 0.04, v_pos.y);
	float splashes = smoothstep(0.4, 0.85, noise(v_pos * 8.0 + 47.0));
	camo = mix(camo, dirt_color, clamp(grime * (low * 0.7 + splashes * 0.35), 0.0, 0.75));

	// Cloth: a faint grain in the normal, and a roughness broken up by the dirt.
	vec3 wobble = vec3(sin(v_pos.x * 260.0) * sin(v_pos.z * 240.0),
	                   sin(v_pos.y * 250.0) * sin(v_pos.x * 230.0), 0.0);
	ALBEDO = camo;
	ROUGHNESS = mix(roughness, roughness * 0.78, splashes);
	SPECULAR = 0.22;
	NORMAL = normalize(NORMAL + wobble * grain * 0.08);
}
