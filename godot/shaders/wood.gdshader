// Weathered boards for the stage: the `Planks` of the boardwalk (stage_planks.tres) and
// the rafts' `Driftwood` (stage_driftwood.tres), swapped in by the models' .import files.
// The UVs from art/stage/build_stage.py carry the grain: u runs along it in meters, and
// v is the board's index plus 0..1 across the board. So each board gets its own tint,
// grain, knot and worn edges, with no textures.
shader_type spatial;

uniform vec3 light_color : source_color = vec3(0.62, 0.45, 0.29);
uniform vec3 dark_color : source_color = vec3(0.34, 0.22, 0.13);
// What sun and salt bleach the wood toward.
uniform vec3 weathered_color : source_color = vec3(0.60, 0.57, 0.52);
uniform float weathering : hint_range(0.0, 1.0) = 0.35;
uniform float tint_variation : hint_range(0.0, 1.0) = 0.35;
uniform float bump_strength = 1.0;

float hash(float n) {
	return fract(sin(n * 91.3458) * 47453.5453);
}

float noise(vec2 p) {
	vec2 i = floor(p);
	vec2 f = fract(p);
	f = f * f * (3.0 - 2.0 * f);
	float n = i.x + i.y * 57.0;
	return mix(mix(hash(n), hash(n + 1.0), f.x), mix(hash(n + 57.0), hash(n + 58.0), f.x), f.y);
}

float fbm(vec2 p) {
	float sum = 0.0;
	float amp = 0.5;
	for (int i = 0; i < 4; i++) {
		sum += amp * noise(p);
		p = p * 2.03 + vec2(17.1, 3.7);
		amp *= 0.5;
	}
	return sum;
}

// Tilts a view-space normal by the screen-space slope of a height (Mikkelsen's bump
// mapping without tangents), so it works on any UV layout.
vec3 bump(vec3 n, vec3 pos, float height) {
	vec3 dpdx = dFdx(pos);
	vec3 dpdy = dFdy(pos);
	vec3 r1 = cross(dpdy, n);
	vec3 r2 = cross(n, dpdx);
	float det = dot(dpdx, r1);
	vec3 grad = sign(det) * (dFdx(height) * r1 + dFdy(height) * r2);
	return normalize(abs(det) * n - grad);
}

void fragment() {
	float id = floor(UV.y);
	float across = fract(UV.y);
	float r = hash(id + 0.37);
	float along = UV.x + r * 23.0;

	// A knot on most boards: a dark eye that the grain lines swirl around.
	vec2 knot = vec2((UV.x - (hash(id + 3.1) - 0.5) * 3.0) * 0.55, (across - 0.25 - 0.5 * hash(id + 5.7)) * 0.4);
	float knot_d = length(knot) / 0.045;
	float has_knot = step(0.3, hash(id + 9.2));
	float swirl = has_knot * exp(-knot_d * knot_d * 0.15);
	float eye = has_knot * (1.0 - smoothstep(0.6, 1.0, knot_d));

	// Growth rings cut lengthwise show as long wavy lines; fibers as fine streaks.
	float warp = fbm(vec2(along * 0.7, across * 1.5 + r * 5.0));
	float ring_coord = across * 3.5 + warp * 2.2 + swirl * 1.6;
	float rings = pow(abs(sin(ring_coord * 3.14159)), 5.0);
	float fibers = noise(vec2(along * 3.0, across * 26.0 + r * 40.0));
	float tone = clamp(0.55 * (1.0 - rings) + 0.3 * fibers + 0.25 * warp - 0.1, 0.0, 1.0);
	vec3 color = mix(dark_color, light_color, tone);
	color *= 1.0 + tint_variation * (r - 0.5);

	// Bleached patches, more on some boards than others, and dark grime blotches.
	float patches = fbm(vec2(along * 0.45, UV.y * 0.6 + 4.0));
	float bleach = clamp(weathering * (0.4 + 1.2 * hash(id + 2.3)) * (0.5 + patches) - 0.15, 0.0, 1.0);
	color = mix(color, weathered_color * (0.85 + 0.25 * fibers), bleach);
	color *= 0.82 + 0.25 * fbm(vec2(along * 0.25, UV.y * 0.35 + 11.0));
	color = mix(color, dark_color * 0.45, eye * 0.85);

	// Edges worn and darkened, the gaps between boards dirtier still.
	float edge = min(across, 1.0 - across);
	color *= mix(0.5, 1.0, smoothstep(0.0, 0.09, edge));

	ALBEDO = color;
	ROUGHNESS = mix(0.72, 0.92, bleach);
	SPECULAR = 0.3;
	float height = fibers * 0.35 + (1.0 - rings) * 0.45 - eye * 0.3 - (1.0 - smoothstep(0.0, 0.06, edge)) * 0.6;
	NORMAL = bump(NORMAL, VERTEX, height * 0.0025 * bump_strength);
}
