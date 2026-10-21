// The soldier's rifle metal (`Gunmetal`: anodized aluminium receivers, rail, optic;
// `Barrel`: parkerized steel; swapped in by godot/models/soldier.glb.import). A dark
// finish with a fine matte grain, printed at each vertex's rest position (see
// soldier.gdshaderinc) — where the rifle lies along +X — so wear runs along the gun:
// streaks of finish rubbed through to brighter, smoother metal, plus the baked
// occlusion in the slots and seams. Metallic but rough: a shiny rifle mirrors the bright
// beach sky and stops reading as black.
shader_type spatial;
render_mode diffuse_burley, specular_schlick_ggx;

#include "res://shaders/soldier.gdshaderinc"

uniform vec3 color : source_color = vec3(0.045, 0.047, 0.05);
uniform vec3 wear_color : source_color = vec3(0.32, 0.32, 0.31);
uniform float roughness : hint_range(0.0, 1.0) = 0.55;
uniform float metallic : hint_range(0.0, 1.0) = 0.45;
uniform float wear : hint_range(0.0, 1.0) = 0.35;
uniform float occlusion : hint_range(0.0, 1.0) = 0.9;
uniform float grain : hint_range(0.0, 0.002) = 0.00025;

void vertex() {
	SOLDIER_VERTEX
}

void fragment() {
	vec3 r = v_rest;
	float pixel = length(fwidth(r));
	// Streaks along the gun (X), short across it.
	float streak = fbm(r * vec3(18.0, 260.0, 260.0) + 7.0);
	float rub = smoothstep(0.7, 0.86, streak) * wear * smoothstep(0.3, 0.7, noise(r * 30.0));
	float mottle = fbm(r * 40.0 + 3.0);
	vec3 albedo = color * (0.85 + 0.3 * mottle);
	albedo = mix(albedo, wear_color, rub);
	float ao = mix(1.0, v_ao, occlusion);
	ALBEDO = albedo * (0.5 + 0.5 * ao);
	AO = ao;
	AO_LIGHT_AFFECT = 0.4;
	METALLIC = mix(metallic, 0.9, rub);
	ROUGHNESS = clamp(roughness + 0.1 * (mottle - 0.5) - 0.25 * rub, 0.1, 1.0);
	SPECULAR = 0.4;
	float h = (noise(r * 1500.0) - 0.5) * grain * detail(0.002, pixel);
	NORMAL = bump(NORMAL, dFdx(VERTEX), dFdy(VERTEX), dFdx(h), dFdy(h));
}
