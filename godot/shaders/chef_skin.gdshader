// The chef's skin and lips (`Skin`, `Lip`; swapped in by fighter.glb.import).
// Ruddy, mottled flesh with subsurface scattering, pores, a five-o'clock shadow
// on the jaw and a slightly oily sheen. COLOR.g = flush (cheeks, nose, ears,
// knuckles), COLOR.b = stubble.
shader_type spatial;
render_mode diffuse_burley, specular_schlick_ggx;

#include "res://shaders/chef_common.gdshaderinc"

uniform vec3 skin_color : source_color = vec3(0.76, 0.54, 0.42);
uniform vec3 flush_color : source_color = vec3(0.74, 0.42, 0.35);
uniform vec3 stubble_color : source_color = vec3(0.42, 0.33, 0.29);
uniform float roughness : hint_range(0.0, 1.0) = 0.52;
uniform float specular : hint_range(0.0, 1.0) = 0.42;
uniform float sss : hint_range(0.0, 1.0) = 0.45;
uniform float pores : hint_range(0.0, 4.0) = 1.0;
uniform float mottle : hint_range(0.0, 1.0) = 0.12;
uniform float ao_strength : hint_range(0.0, 1.0) = 0.65;

void fragment() {
	vec3 p = rest_position(UV, UV2);
	float footprint = length(fwidth(p));
	float flush = COLOR.g;
	float stubble = COLOR.b;

	// Uneven tone: blotches a couple of centimeters across, and finer freckling.
	float blotch = chef_fbm(p * 45.0);
	float fleck = chef_noise(p * 260.0 + 3.1);
	vec3 c = skin_color * (1.0 - mottle + 2.0 * mottle * blotch);
	c = mix(c, flush_color, clamp(flush * (0.35 + 0.5 * chef_fbm(p * 90.0 + 5.0)), 0.0, 1.0));
	c *= 1.0 - 0.06 * (fleck - 0.5) * detail_fade(footprint, 260.0);
	// Stubble: a bluish-gray shadow under the skin, dotted with hair tips up close.
	float dots = smoothstep(0.6, 0.85, chef_noise(p * 1400.0));
	float stubble_mix = stubble * (0.32 + 0.4 * dots * detail_fade(footprint, 1400.0));
	c = mix(c, stubble_color, stubble_mix);

	// Pores and fine wrinkles, faded out with distance.
	float h = (chef_noise(p * 900.0) - 0.5) * 0.00012 * detail_fade(footprint, 900.0)
			+ (chef_noise(p * vec3(160.0, 160.0, 520.0)) - 0.5) * 0.00018 * detail_fade(footprint, 520.0)
			+ (blotch - 0.5) * 0.0004;
	NORMAL = bump_normal(NORMAL, VERTEX, h * pores);

	ALBEDO = c;
	// Oilier on the nose and cheeks, drier where the stubble is.
	ROUGHNESS = clamp(roughness - 0.12 * flush + 0.12 * stubble + 0.08 * (blotch - 0.5), 0.05, 1.0);
	SPECULAR = specular;
	SSS_STRENGTH = sss;
	// Thin flesh (ears, nose, fingers) glows red when lit from behind.
	BACKLIGHT = vec3(0.45, 0.12, 0.06) * flush;
	AO = mix(1.0, COLOR.r, ao_strength);
	AO_LIGHT_AFFECT = 0.2;
}
