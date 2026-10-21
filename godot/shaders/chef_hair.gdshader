// The chef's hair, brows and handlebar mustache (`Hair`; swapped in by
// fighter.glb.import). Strands are streaks of noise stretched along the way the hair
// lies: down and back on the scalp, sideways in the brows and mustache (COLOR.b = 1).
// COLOR.g = gray, salting the temples.
shader_type spatial;
render_mode diffuse_burley, specular_schlick_ggx;

#include "res://shaders/chef_common.gdshaderinc"

uniform vec3 color : source_color = vec3(0.16, 0.10, 0.065);
uniform vec3 tip_color : source_color = vec3(0.26, 0.17, 0.11);
uniform vec3 gray_color : source_color = vec3(0.55, 0.53, 0.50);
uniform float roughness : hint_range(0.0, 1.0) = 0.62;
uniform float specular : hint_range(0.0, 1.0) = 0.3;
uniform float ao_strength : hint_range(0.0, 1.0) = 1.0;

void fragment() {
	vec3 p = rest_position(UV, UV2);
	float footprint = length(fwidth(p));
	// Stretch the noise along the strands: long in z on the scalp, long in y sideways.
	vec3 scalp = p * vec3(900.0, 900.0, 70.0);
	vec3 side = p * vec3(900.0, 50.0, 900.0);
	vec3 q = mix(scalp, side, COLOR.b);
	float strands = chef_noise(q) * 0.6 + chef_noise(q * 2.1 + 4.0) * 0.4;
	float fade = detail_fade(footprint, 900.0);
	float s = mix(0.5, strands, fade);
	vec3 c = mix(color, tip_color, s * 0.8);
	float gray = COLOR.g * smoothstep(0.35, 0.65, chef_noise(q * 0.5 + 9.0) * fade + 0.5 * (1.0 - fade) + COLOR.g * 0.3);
	c = mix(c, gray_color, clamp(gray, 0.0, 1.0));
	float h = (strands - 0.5) * 0.00025 * fade + (chef_noise(p * 150.0) - 0.5) * 0.0006;
	NORMAL = bump_normal(NORMAL, VERTEX, h);
	ALBEDO = c;
	ROUGHNESS = clamp(roughness + 0.15 * (s - 0.5), 0.1, 1.0);
	SPECULAR = specular;
	RIM = 0.1;
	RIM_TINT = 0.6;
	AO = mix(1.0, COLOR.r, ao_strength);
	AO_LIGHT_AFFECT = 0.5;
}
