// Backdrop ocean: rippling water, see-through shallows over the sand, foam where it
// meets the beach, and a slow rise and fall that washes the waterline up the slope.
// Decorative only; it runs on TIME, never on the sim clock.
shader_type spatial;
render_mode cull_back;

uniform vec3 shallow_color : source_color = vec3(0.22, 0.78, 0.74);
uniform vec3 deep_color : source_color = vec3(0.02, 0.24, 0.40);
uniform vec3 foam_color : source_color = vec3(0.95, 0.97, 0.98);
// Water thickness (along the view ray) at which it reaches the deep color.
uniform float depth_fade = 7.0;
// Thickness over which the sand underneath fades out of view.
uniform float clear_depth = 2.0;
uniform float foam_width = 0.9;
// How far the surface rises and falls (the swash).
uniform float swash = 0.08;
uniform sampler2D ripple_a : hint_normal, filter_linear_mipmap, repeat_enable;
uniform sampler2D ripple_b : hint_normal, filter_linear_mipmap, repeat_enable;
uniform sampler2D foam_noise : filter_linear_mipmap, repeat_enable;
uniform sampler2D depth_tex : hint_depth_texture, filter_linear;

varying vec3 world_pos;

void vertex() {
	VERTEX.y += swash * sin(TIME * 0.7);
	world_pos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
}

void fragment() {
	vec2 p = world_pos.xz;
	vec3 n1 = texture(ripple_a, p * 0.04 + TIME * vec2(0.010, 0.006)).rgb;
	vec3 n2 = texture(ripple_b, p * 0.11 - TIME * vec2(0.008, 0.014)).rgb;
	float dist = length(world_pos - CAMERA_POSITION_WORLD);
	NORMAL_MAP = mix(n1, n2, 0.5);
	// Fade ripples out with distance so the horizon doesn't shimmer.
	NORMAL_MAP_DEPTH = mix(0.7, 0.08, clamp(dist / 500.0, 0.0, 1.0));

	// How much water lies between this surface point and whatever is behind it.
	float raw = texture(depth_tex, SCREEN_UV).r;
	vec4 behind = INV_PROJECTION_MATRIX * vec4(SCREEN_UV * 2.0 - 1.0, raw, 1.0);
	behind.xyz /= behind.w;
	float thickness = max(length(behind.xyz) - length(VERTEX), 0.0);

	float deep = clamp(thickness / depth_fade, 0.0, 1.0);
	vec3 water = mix(shallow_color, deep_color, sqrt(deep));

	float edge = 1.0 - smoothstep(0.0, foam_width, thickness);
	float churn = texture(foam_noise, p * 0.12 + vec2(TIME * 0.03, sin(TIME * 0.7) * 0.05)).r;
	float foam = smoothstep(0.45, 0.7, edge * (0.55 + churn));

	ALBEDO = mix(water, foam_color, foam);
	ROUGHNESS = mix(0.06, 0.9, foam);
	SPECULAR = 0.5;
	ALPHA = max(mix(0.25, 1.0, clamp(thickness / clear_depth, 0.0, 1.0)), foam);
}
