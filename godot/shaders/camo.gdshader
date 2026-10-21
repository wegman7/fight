// The soldier's fatigues (its `Camo` material, swapped in by
// godot/models/soldier.glb.import). A woodland camo printed at each vertex's rest
// position (see soldier.gdshaderinc), so it stays on the cloth when he moves:
// domain-warped olive, brown and tan blotches over a dark green base with thin black
// "branch" strokes, sun-faded patches, dirt gathered towards the boots, darkened in the
// creases by the baked occlusion, and a twill weave plus soft wrinkles in the normal.
shader_type spatial;
render_mode diffuse_burley, specular_schlick_ggx;

#include "res://shaders/soldier.gdshaderinc"

uniform vec3 base_color : source_color = vec3(0.20, 0.24, 0.14);
uniform vec3 olive_color : source_color = vec3(0.29, 0.32, 0.19);
uniform vec3 brown_color : source_color = vec3(0.25, 0.19, 0.12);
uniform vec3 tan_color : source_color = vec3(0.38, 0.35, 0.25);
uniform vec3 black_color : source_color = vec3(0.06, 0.065, 0.055);
uniform vec3 dirt_color : source_color = vec3(0.15, 0.13, 0.09);
uniform float scale : hint_range(1.0, 40.0) = 13.0;
uniform float roughness : hint_range(0.0, 1.0) = 0.93;
uniform float grime : hint_range(0.0, 1.0) = 0.45;
uniform float occlusion : hint_range(0.0, 1.0) = 0.85;
uniform float weave_period = 0.0025;
uniform float wrinkles : hint_range(0.0, 0.01) = 0.0016;

void vertex() {
	SOLDIER_VERTEX
}

void fragment() {
	vec3 r = v_rest;
	float pixel = length(fwidth(r));
	// Domain warp makes the blotches organic instead of noise-round.
	vec3 p = r * scale;
	vec3 warp = vec3(noise(p * 0.7 + 11.0), noise(p * 0.7 + 23.0), noise(p * 0.7 + 37.0)) - 0.5;
	p += warp * 1.4;
	float n = noise(p) * 0.55 + noise(p * 2.3 + 7.3) * 0.32 + noise(p * 5.1 + 1.7) * 0.13;
	vec3 camo = base_color;
	camo = mix(camo, olive_color, smoothstep(0.42, 0.46, n));
	camo = mix(camo, brown_color, smoothstep(0.58, 0.62, n));
	camo = mix(camo, tan_color, smoothstep(0.30, 0.27, n) * 0.85);
	float branch = noise(p * 1.9 + 51.0);
	camo = mix(camo, black_color, smoothstep(0.035, 0.0, abs(branch - 0.5)) * smoothstep(0.5, 0.6, noise(p * 0.8 + 3.0)));

	// Wear: sun fade in blotches, thread-level speckle, dirt low on the body.
	float fade = fbm(r * 9.0 + 21.0);
	camo *= 0.9 + 0.25 * fade;
	camo *= 0.94 + 0.12 * hash(floor(r * 900.0)) * detail(0.004, pixel);
	float low = smoothstep(0.62, 0.04, r.y);
	float splashes = smoothstep(0.45, 0.85, fbm(r * 11.0 + 47.0));
	float dirt = clamp(grime * (low * 0.75 + splashes * 0.35), 0.0, 0.8);
	camo = mix(camo, dirt_color, dirt);

	float ao = mix(1.0, v_ao, occlusion);
	ALBEDO = camo * (0.55 + 0.45 * ao);
	AO = ao;
	AO_LIGHT_AFFECT = 0.35;
	ROUGHNESS = clamp(roughness - 0.08 * splashes + 0.05 * fade, 0.0, 1.0);
	SPECULAR = 0.25;
	float h = weave(r, weave_period) * detail(weave_period * 3.0, pixel)
		+ (fbm(r * 60.0) - 0.5) * wrinkles * detail(0.02, pixel);
	NORMAL = bump(NORMAL, dFdx(VERTEX), dFdy(VERTEX), dFdx(h), dFdy(h));
}
