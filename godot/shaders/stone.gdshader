// Sandstone for the stage's blocks and the rock under them (`Stone`, swapped in by
// godot/models/stage.glb.import via stage_stone.tres). All procedural, from the model-space
// position: wavy sediment layers, blotchy color, pits, damp algae in the hollows and
// toward the rock's tip, and sand dust on anything facing up. UV.x carries each cut
// block's index (0 for the rough rock) so blocks differ a little in tint.
shader_type spatial;

uniform vec3 light_color : source_color = vec3(0.80, 0.68, 0.51);
uniform vec3 dark_color : source_color = vec3(0.56, 0.44, 0.33);
uniform vec3 band_color : source_color = vec3(0.68, 0.48, 0.34);
uniform vec3 algae_color : source_color = vec3(0.20, 0.27, 0.15);
uniform vec3 dust_color : source_color = vec3(0.90, 0.81, 0.64);
// Model-space heights between which algae creeps in toward the rock's tip.
uniform float algae_top = -2.5;
uniform float algae_bottom = -6.0;
uniform float bump_strength = 1.0;

varying vec3 obj_pos;
varying vec3 world_normal;

float hash(float n) {
	return fract(sin(n * 78.233) * 43758.5453);
}

float hash3(vec3 p) {
	p = fract(p * 0.3183099 + 0.1);
	p *= 17.0;
	return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}

float noise3(vec3 x) {
	vec3 i = floor(x);
	vec3 f = fract(x);
	f = f * f * (3.0 - 2.0 * f);
	return mix(mix(mix(hash3(i), hash3(i + vec3(1, 0, 0)), f.x),
					mix(hash3(i + vec3(0, 1, 0)), hash3(i + vec3(1, 1, 0)), f.x), f.y),
			mix(mix(hash3(i + vec3(0, 0, 1)), hash3(i + vec3(1, 0, 1)), f.x),
					mix(hash3(i + vec3(0, 1, 1)), hash3(i + vec3(1, 1, 1)), f.x), f.y), f.z);
}

float fbm3(vec3 p) {
	float sum = 0.0;
	float amp = 0.5;
	for (int i = 0; i < 5; i++) {
		sum += amp * noise3(p);
		p = p * 2.02 + vec3(5.3, 1.7, 9.1);
		amp *= 0.5;
	}
	return sum;
}

// Distance to the nearest of a jittered grid of points: small round pits where it's low.
float cells(vec3 p) {
	vec3 i = floor(p);
	vec3 f = fract(p);
	float d = 1.0;
	for (int x = -1; x <= 1; x++) {
		for (int y = -1; y <= 1; y++) {
			for (int z = -1; z <= 1; z++) {
				vec3 o = vec3(float(x), float(y), float(z));
				vec3 c = o + vec3(hash3(i + o), hash3(i + o + 19.1), hash3(i + o + 47.7));
				d = min(d, length(c - f));
			}
		}
	}
	return d;
}

// Same as in wood.gdshader: bump mapping from the screen-space slope of a height.
vec3 bump(vec3 n, vec3 pos, float height) {
	vec3 dpdx = dFdx(pos);
	vec3 dpdy = dFdy(pos);
	vec3 r1 = cross(dpdy, n);
	vec3 r2 = cross(n, dpdx);
	float det = dot(dpdx, r1);
	vec3 grad = sign(det) * (dFdx(height) * r1 + dFdy(height) * r2);
	return normalize(abs(det) * n - grad);
}

void vertex() {
	obj_pos = VERTEX;
	world_normal = normalize((MODEL_MATRIX * vec4(NORMAL, 0.0)).xyz);
}

void fragment() {
	vec3 p = obj_pos;
	float r = hash(floor(UV.x) + 0.5);
	float big = fbm3(p * 0.35 + r * 13.0);
	float mid = fbm3(p * 1.7 + 5.0);
	float fine = noise3(p * 11.0);

	// Sediment layers: horizontal bands, bent by the noise.
	float layer = p.y + (mid - 0.5) * 0.5 + (big - 0.5) * 0.8;
	float strata = smoothstep(0.2, 1.0, sin(layer * 14.0) * 0.5 + 0.5);
	float pits = 1.0 - smoothstep(0.02, 0.1 + 0.06 * fine, cells(p * 3.5 + r * 3.0));
	// Hairline cracks: where a noise crosses its midpoint, which makes long wandering lines.
	float crack_noise = fbm3(p * vec3(1.1, 2.2, 1.1) + 31.0) - 0.5 + (fine - 0.5) * 0.04;
	float cracks = (1.0 - smoothstep(0.003, 0.012, abs(crack_noise))) * smoothstep(0.48, 0.62, big);
	float speckle = noise3(p * 37.0);

	vec3 color = mix(dark_color, light_color, smoothstep(0.25, 0.75, big * 0.7 + mid * 0.5 - 0.1));
	color = mix(color, band_color, strata * 0.55 * (0.5 + mid));
	color *= 0.88 + 0.24 * r;
	color *= 0.8 + 0.3 * fine + 0.15 * speckle;
	color = mix(color, color * 0.4, pits);
	color = mix(color, dark_color * 0.35, cracks * 0.8);

	// Damp algae in the hollows, thickening toward the tip of the rock.
	float hollow = smoothstep(0.48, 0.3, mid);
	float low = smoothstep(algae_top, algae_bottom, p.y);
	float algae = clamp(hollow * 0.55 + low * (0.35 + 0.6 * big), 0.0, 1.0);
	color = mix(color, algae_color * (0.8 + 0.4 * fine), algae * 0.75);

	// Sand dust settles on whatever faces up.
	float up = smoothstep(0.35, 0.85, world_normal.y);
	color = mix(color, dust_color, up * smoothstep(0.35, 0.65, fine * 0.4 + big * 0.6) * 0.7);

	ALBEDO = color;
	ROUGHNESS = mix(0.92, 0.6, algae * 0.6);
	SPECULAR = 0.35;
	float height = mid * 0.9 + strata * 0.08 + fine * 0.12 - pits * 0.25 - cracks * 0.12;
	NORMAL = bump(NORMAL, VERTEX, height * 0.05 * bump_strength);
}
