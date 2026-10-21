// The chef's cotton: his whites and toque (`Jacket`) and his trousers (`Pants`);
// swapped in by fighter.glb.import. A twill weave in the normal and roughness,
// slightly uneven dye, a soft sheen at grazing angles, and (pattern = 1) a small
// woven check like real chef's trousers, mapped around each leg, or (pattern = 2)
// a striped kitchen towel (`Towel`). COLOR.g = stains
// and wear (a few faint sauce splashes, grubby cuffs).
shader_type spatial;
render_mode diffuse_burley, specular_schlick_ggx;

#include "res://shaders/chef_common.gdshaderinc"

uniform vec3 color : source_color = vec3(0.80, 0.80, 0.78);
uniform vec3 check_color : source_color = vec3(0.12, 0.12, 0.13);
uniform vec3 stain_color : source_color = vec3(0.62, 0.48, 0.30);
uniform int pattern = 0;
uniform float check_size = 0.009;
uniform float roughness : hint_range(0.0, 1.0) = 0.9;
uniform float specular : hint_range(0.0, 1.0) = 0.3;
uniform float weave : hint_range(0.0, 4.0) = 1.0;
uniform float sheen : hint_range(0.0, 1.0) = 0.25;
uniform float dye : hint_range(0.0, 0.5) = 0.06;
uniform float ao_strength : hint_range(0.0, 1.0) = 1.0;

// Fraction of a band of width `w` around `x` that falls in the "on" half of a
// square wave of period 1: an anti-aliased stripe.
float stripe(float x, float w) {
	w = max(w, 1e-4);
	float a = x - 0.5 * w;
	float b = x + 0.5 * w;
	float ia = floor(a) * 0.5 + max(fract(a) - 0.5, 0.0);
	float ib = floor(b) * 0.5 + max(fract(b) - 0.5, 0.0);
	return (ib - ia) / w;
}

void fragment() {
	vec3 p = rest_position(UV, UV2);
	float footprint = length(fwidth(p));
	vec3 c = color * (1.0 - dye + 2.0 * dye * chef_fbm(p * 18.0));

	// Twill: fine diagonal ribs, two directions of thread.
	float u = p.x + p.y;
	float diag = (p.z + u) * 1500.0;
	float threads = sin(diag * 6.2832) * 0.5 + 0.5;
	float slub = chef_noise(p * vec3(300.0, 300.0, 40.0));
	float h = (threads * 0.7 + slub * 0.3 - 0.5) * 0.00008 * detail_fade(footprint, 1500.0)
			+ (chef_noise(p * 120.0) - 0.5) * 0.00025;

	if (pattern == 1) {
		// Around each trouser leg (legs at y = +-0.09), seam on the inside.
		float side = p.y > 0.0 ? 1.0 : -1.0;
		float around = atan(p.x, (p.y - side * 0.09) * side) * 0.068;
		vec2 q = vec2(around, p.z) / check_size;
		float w = footprint / check_size * 1.5;
		float cx = stripe(q.x, w);
		float cy = stripe(q.y, w);
		// Woven check: dark where both threads are dark, mid where one is.
		float dark = cx * cy;
		float mid = cx + cy - 2.0 * dark;
		c = mix(c, check_color, dark + 0.5 * mid);
	}

	if (pattern == 2) {
		// Two woven stripes across a kitchen towel, every `check_size` meters.
		float w = footprint / check_size * 1.5;
		float band = stripe(p.z / check_size * 4.0, w * 4.0) * stripe(p.z / check_size + 0.3, w);
		c = mix(c, check_color, band);
	}

	float stain = COLOR.g * smoothstep(0.25, 0.7, chef_fbm(p * 140.0 + 9.0) + COLOR.g * 0.4);
	c = mix(c, c * stain_color, clamp(stain, 0.0, 0.8));

	NORMAL = bump_normal(NORMAL, VERTEX, h * weave);
	ALBEDO = c;
	ROUGHNESS = clamp(roughness - 0.08 * stain + 0.05 * (slub - 0.5), 0.05, 1.0);
	SPECULAR = specular;
	RIM = sheen;
	RIM_TINT = 0.7;
	AO = mix(1.0, COLOR.r, ao_strength);
	AO_LIGHT_AFFECT = 0.5;
}
