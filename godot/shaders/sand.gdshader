// Backdrop beach: flat sand with low dunes under the stage, sloping into the sea past
// the palms. Heights come from world position, so the plane just needs subdivisions.
// The ocean's waterline is wherever this slope crosses the water level.
shader_type spatial;

uniform vec3 dry_color : source_color = vec3(0.93, 0.84, 0.66);
uniform vec3 dry_color_2 : source_color = vec3(0.84, 0.74, 0.56);
uniform vec3 wet_color : source_color = vec3(0.62, 0.52, 0.37);
// World heights between which the sand goes from wet to dry.
uniform float wet_low = -12.3;
uniform float wet_high = -11.95;
// Distance behind the stage (-z) where the slope into the water starts.
uniform float shore_start = 70.0;
uniform float dune_height = 0.45;
uniform sampler2D dunes : filter_linear_mipmap, repeat_enable;
uniform sampler2D grain : filter_linear_mipmap, repeat_enable;
uniform sampler2D ripples : hint_normal, filter_linear_mipmap, repeat_enable;

varying vec3 world_pos;

float height(vec2 p) {
	float back = max(-p.y - shore_start, 0.0);
	float dune = (textureLod(dunes, p * 0.006, 0.0).r - 0.5) * 2.0 * dune_height;
	return dune * (1.0 - smoothstep(shore_start - 12.0, shore_start, -p.y)) - back * 0.06 - back * back * 0.002;
}

void vertex() {
	vec2 p = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xz;
	float e = 0.5;
	VERTEX.y += height(p);
	NORMAL = normalize(vec3(height(p - vec2(e, 0.0)) - height(p + vec2(e, 0.0)), 2.0 * e,
			height(p - vec2(0.0, e)) - height(p + vec2(0.0, e))));
	world_pos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
}

void fragment() {
	vec2 p = world_pos.xz;
	float g = texture(grain, p * 0.025).r;
	vec3 dry = mix(dry_color_2, dry_color, smoothstep(0.2, 0.8, g));
	float wet = 1.0 - smoothstep(wet_low, wet_high, world_pos.y);
	ALBEDO = mix(dry, wet_color, wet);
	ROUGHNESS = mix(0.95, 0.35, wet);
	NORMAL_MAP = texture(ripples, p * 0.12).rgb;
	NORMAL_MAP_DEPTH = 0.25;
}
