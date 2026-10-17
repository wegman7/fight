// The pug's short black coat (its `Fur` material, swapped in by godot/models/pug.glb.import).
// A soft sheen rather than a plastic highlight, and a fuzzy, lighter edge where the
// surface turns away from the camera, the way fine hairs catch light on a silhouette.
shader_type spatial;

uniform vec3 color : source_color = vec3(0.022, 0.019, 0.018);
// What the hairs on the silhouette blend toward.
uniform vec3 fuzz_color : source_color = vec3(0.17, 0.16, 0.16);
uniform float fuzz : hint_range(0.0, 1.0) = 0.55;
uniform float roughness : hint_range(0.0, 1.0) = 0.55;

void fragment() {
	float edge = pow(1.0 - clamp(dot(NORMAL, VIEW), 0.0, 1.0), 3.0);
	ALBEDO = mix(color, fuzz_color, edge * fuzz);
	ROUGHNESS = roughness;
	SPECULAR = 0.35;
	RIM = 0.5;
	RIM_TINT = 0.4;
}
