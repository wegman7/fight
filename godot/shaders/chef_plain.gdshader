// Everything else on the chef and his pie (leather shoes and soles, eyes, buttons,
// nails, the pie's tin, crust, cream and cherry; swapped in by fighter.glb.import and
// pie.glb.import): one physically based surface with baked AO, a grain in the normal,
// blotchy color variation and an optional mask (COLOR.g: creased shoe leather, the
// pink corners of the eyes) that blends toward `mask_color` / `mask_roughness`.
shader_type spatial;
render_mode diffuse_burley, specular_schlick_ggx;

#include "res://shaders/chef_common.gdshaderinc"

uniform vec3 color : source_color = vec3(0.5);
uniform vec3 mask_color : source_color = vec3(0.5);
uniform float mask_amount : hint_range(0.0, 1.0) = 0.0;
uniform float roughness : hint_range(0.0, 1.0) = 0.5;
uniform float mask_roughness : hint_range(0.0, 1.0) = 0.5;
uniform float metallic : hint_range(0.0, 1.0) = 0.0;
uniform float specular : hint_range(0.0, 1.0) = 0.5;
uniform float sss : hint_range(0.0, 1.0) = 0.0;
uniform float clearcoat : hint_range(0.0, 1.0) = 0.0;
uniform float clearcoat_roughness : hint_range(0.0, 1.0) = 0.1;
uniform float variation : hint_range(0.0, 1.0) = 0.05;
uniform float variation_scale = 40.0;
uniform float grain : hint_range(0.0, 4.0) = 0.0;
uniform float grain_scale = 600.0;
uniform float ao_strength : hint_range(0.0, 1.0) = 1.0;

void fragment() {
	vec3 p = rest_position(UV, UV2);
	float footprint = length(fwidth(p));
	float m = clamp(COLOR.g * mask_amount, 0.0, 1.0);
	float blotch = chef_fbm(p * variation_scale);
	vec3 c = mix(color, mask_color, m) * (1.0 - variation + 2.0 * variation * blotch);
	float g = chef_noise(p * grain_scale);
	float h = (g - 0.5) * (0.25 / grain_scale) * detail_fade(footprint, grain_scale)
			+ (chef_noise(p * grain_scale * 0.2 + 7.0) - 0.5) * (0.6 / grain_scale);
	NORMAL = bump_normal(NORMAL, VERTEX, h * grain);
	ALBEDO = c;
	METALLIC = metallic;
	ROUGHNESS = clamp(mix(roughness, mask_roughness, m) + 0.1 * (blotch - 0.5) * variation * 4.0, 0.03, 1.0);
	SPECULAR = specular;
	SSS_STRENGTH = sss;
	CLEARCOAT = clearcoat;
	CLEARCOAT_ROUGHNESS = clearcoat_roughness;
	AO = mix(1.0, COLOR.r, ao_strength);
	AO_LIGHT_AFFECT = 0.5;
}
