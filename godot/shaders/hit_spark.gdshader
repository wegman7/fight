// Hit effect: a camera-facing quad drawn as a Smash-style impact starburst, a white-hot
// core flash, sharp tapered spikes that fly outward and thin away, and a quick shock
// ring. Strong hits add long streaks along the launch direction. `age` (0..1) is set
// from Rust each render frame (gdext `update_sparks`); nothing here runs on its own.
shader_type spatial;
render_mode unshaded, blend_mix, depth_draw_never, depth_test_disabled, cull_disabled, shadows_disabled, fog_disabled;

// 0 on the first frame shown, 1 at the end of the effect's life.
uniform float age = 0.0;
// Edge color; the core and spike centres run toward white.
uniform vec3 tint : source_color = vec3(1.0, 0.55, 0.12);
// HDR brightness (glow picks it up).
uniform float energy = 2.5;
uniform int spikes = 10;
// Varies spike angles and lengths per spark.
uniform float seed = 0.0;
// World-space launch direction; zero length = no launch streaks.
uniform vec3 launch = vec3(0.0);

varying vec2 launch_view;

float hash(float n) {
	return fract(sin(n * 12.9898 + 78.233) * 43758.5453);
}

void vertex() {
	// Billboard, keeping the node's scale.
	float s = length(MODEL_MATRIX[0].xyz);
	MODELVIEW_MATRIX = VIEW_MATRIX * mat4(INV_VIEW_MATRIX[0] * s, INV_VIEW_MATRIX[1] * s, INV_VIEW_MATRIX[2] * s, MODEL_MATRIX[3]);
	MODELVIEW_NORMAL_MATRIX = mat3(MODELVIEW_MATRIX);
	vec2 d = (VIEW_MATRIX * vec4(launch, 0.0)).xy;
	launch_view = length(launch) > 0.0 ? normalize(d) : vec2(0.0);
}

// A spike from the centre along `dir`, spanning `inner`..`outer` radius, `width` wide at
// its base and tapering to a point. Returns (coverage, centre-line heat).
vec2 spike(vec2 p, vec2 dir, float inner, float outer, float width) {
	float along = dot(p, dir);
	float across = abs(dot(p, vec2(-dir.y, dir.x)));
	float span = max(outer - inner, 1e-4);
	float f = (along - inner) / span;
	if (f < 0.0 || f > 1.0) {
		return vec2(0.0);
	}
	// Widest a quarter of the way out, sharp at both ends (a long diamond).
	float profile = f < 0.25 ? f / 0.25 : 1.0 - (f - 0.25) / 0.75;
	float w = width * profile;
	float cover = 1.0 - smoothstep(w * 0.55, w, across);
	float heat = 1.0 - smoothstep(0.0, w * 0.45, across);
	return vec2(cover, heat * profile);
}

void fragment() {
	vec2 p = vec2(UV.x - 0.5, 0.5 - UV.y) * 2.0;
	float r = length(p);
	float t = clamp(age, 0.0, 1.0);
	float fade = 1.0 - smoothstep(0.45, 1.0, t);

	// Core flash: biggest on the first frame or two, then collapses.
	float core_r = mix(0.2, 0.03, smoothstep(0.0, 0.5, t));
	float core = exp(-(r * r) / (core_r * core_r));
	float halo = exp(-(r * r) / (core_r * core_r * 3.0)) * 0.3 * (1.0 - t);

	// Spikes: already long on the first frame, then fly outward, shorten and thin.
	float cover = 0.0;
	float heat = 0.0;
	int n = max(spikes, 3);
	// With launch streaks, the other spikes stay shorter so the streaks stand out.
	bool launched = launch_view != vec2(0.0);
	float reach = launched ? 0.7 : 1.0;
	for (int i = 0; i < n; i++) {
		float fi = float(i);
		float h1 = hash(seed + fi * 1.7);
		float h2 = hash(seed * 3.1 + fi * 5.3);
		float a = (fi + 0.6 * (h1 - 0.5)) * TAU / float(n) + seed * TAU;
		vec2 dir = vec2(cos(a), sin(a));
		// Long and short spikes alternate, as in a comic-book starburst.
		bool major = i % 2 == 0;
		float len = major ? mix(0.75, 0.95, h2) : mix(0.4, 0.6, h2);
		float outer = len * reach * mix(1.0, 0.8, t);
		float inner = mix(0.0, outer * 0.8, smoothstep(0.1, 0.9, t));
		float width = (major ? mix(0.2, 0.15, h1) : mix(0.13, 0.1, h1)) * mix(1.0, 0.25, t);
		vec2 s = spike(p, dir, inner, outer, width);
		cover = max(cover, s.x);
		heat = max(heat, s.y);
	}

	// Launch streaks: long and bright along where the defender flies.
	if (launched) {
		for (int i = -1; i <= 1; i++) {
			float off = float(i) * 0.16;
			vec2 dir = vec2(cos(off) * launch_view.x - sin(off) * launch_view.y, sin(off) * launch_view.x + cos(off) * launch_view.y);
			float outer = (i == 0 ? 1.0 : 0.8) * mix(0.9, 1.0, smoothstep(0.0, 0.3, t));
			float inner = mix(0.05, outer * 0.75, smoothstep(0.05, 0.9, t));
			float width = (i == 0 ? 0.13 : 0.08) * mix(1.0, 0.3, t);
			vec2 s = spike(p, dir, inner, outer, width);
			cover = max(cover, s.x);
			heat = max(heat, s.y * 1.6);
		}
	}

	// Shock ring: a thin circle racing out over the first half.
	float ring_r = mix(0.2, 0.9, sqrt(t));
	float ring = (1.0 - smoothstep(0.0, mix(0.035, 0.01, t), abs(r - ring_r))) * (1.0 - smoothstep(0.0, 0.4, t)) * 0.25;

	// White-hot at the core and briefly along the spikes, the tint everywhere else.
	float white = clamp(core + heat * 0.4 * (1.0 - t), 0.0, 1.0);
	// Nothing reaches the quad's edge, so its square never shows.
	float edge = 1.0 - smoothstep(0.88, 1.0, r);
	float alpha = clamp(core + halo + cover + ring, 0.0, 1.0) * fade * edge;
	vec3 color = mix(tint, vec3(1.0, 0.97, 0.9), white);
	ALBEDO = color * energy * mix(1.2, 0.7, t);
	ALPHA = alpha;
}
