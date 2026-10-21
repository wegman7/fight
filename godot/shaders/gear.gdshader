// The soldier's gear (`Vest`, `VestPouch`, `Balaclava`, `Boot`, `Helmet`, `Polymer` and
// the near-black hardware — pads, straps, gloves, soles — swapped in by
// godot/models/soldier.glb.import): one worn fabric / leather / coated-shell shader,
// printed at each vertex's rest position (see soldier.gdshaderinc). Each material's
// `.tres` sets its color, finish and how much it is woven, scuffed and dirtied:
// sun-faded blotches, scuffs that go lighter and glossier (leather toes, the helmet's
// paint), dirt gathered low on the body, the baked occlusion in the creases, and a
// weave or grain plus soft wrinkles in the normal.
shader_type spatial;
render_mode diffuse_burley, specular_schlick_ggx;

#include "res://shaders/soldier.gdshaderinc"

uniform vec3 color : source_color = vec3(0.40, 0.36, 0.26);
uniform vec3 dirt_color : source_color = vec3(0.13, 0.12, 0.09);
uniform float roughness : hint_range(0.0, 1.0) = 0.93;
uniform float specular : hint_range(0.0, 1.0) = 0.22;
uniform float grime : hint_range(0.0, 1.0) = 0.35;
uniform float variation : hint_range(0.0, 1.0) = 0.28;
uniform float scuff : hint_range(0.0, 1.0) = 0.0;
uniform float occlusion : hint_range(0.0, 1.0) = 0.85;
// Weave period in meters (0 = no weave: leather, moulded polymer, painted shells).
uniform float weave_period = 0.002;
uniform float grain : hint_range(0.0, 0.004) = 0.0008;
uniform float wrinkles : hint_range(0.0, 0.01) = 0.0012;

void vertex() {
	SOLDIER_VERTEX
}

void fragment() {
	vec3 r = v_rest;
	float pixel = length(fwidth(r));
	float fade = fbm(r * 7.0) * 0.6 + noise(r * 23.0 + 5.3) * 0.4;
	vec3 albedo = color * (1.0 + (fade - 0.5) * 2.0 * variation);
	float scuffs = smoothstep(0.62, 0.8, fbm(r * vec3(40.0, 18.0, 40.0) + 13.0)) * scuff;
	albedo = mix(albedo, color * 1.7 + vec3(0.03), scuffs);
	float low = smoothstep(0.6, 0.03, r.y);
	float splashes = smoothstep(0.45, 0.86, fbm(r * 9.0 + 31.0));
	albedo = mix(albedo, dirt_color, clamp(grime * (low * 0.7 + splashes * 0.4), 0.0, 0.8));

	float ao = mix(1.0, v_ao, occlusion);
	ALBEDO = albedo * (0.55 + 0.45 * ao);
	AO = ao;
	AO_LIGHT_AFFECT = 0.35;
	ROUGHNESS = clamp(roughness - 0.1 * splashes - 0.25 * scuffs + 0.06 * (fade - 0.5), 0.05, 1.0);
	SPECULAR = specular;
	float h = (fbm(r * 55.0) - 0.5) * wrinkles * detail(0.02, pixel)
		+ (noise(r * 700.0) - 0.5) * grain * detail(0.004, pixel);
	if (weave_period > 0.0) {
		h += weave(r, weave_period) * detail(weave_period * 3.0, pixel);
	}
	NORMAL = bump(NORMAL, dFdx(VERTEX), dFdy(VERTEX), dFdx(h), dFdy(h));
}
