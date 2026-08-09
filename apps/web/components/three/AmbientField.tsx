"use client";

import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { allowsAmbient } from "@/lib/quality";
import { useAppearance } from "@/components/system/ThemeProvider";

/**
 * The ambient field: a slow two-layer flow behind the entire shell.
 *
 * This is what makes the product feel alive rather than static, and it is the
 * surface that carries reactive session colour (see lib/useAmbientState).
 *
 * Deliberately cheap: one fullscreen triangle, no lights, no post-processing,
 * no depth buffer. It reads --ambient-* from the document rather than taking
 * React props so status changes do not re-render the tree at animation rates.
 */

const VERTEX = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = vec4(position.xy, 0.0, 1.0);
  }
`;

const FRAGMENT = /* glsl */ `
  precision highp float;

  varying vec2 vUv;
  uniform float uTime;
  uniform float uIntensity;
  uniform float uHue;
  uniform float uSat;
  uniform vec2  uResolution;

  // Cheap value noise -- no texture fetch, no hash spikes.
  vec2 hash(vec2 p) {
    p = vec2(dot(p, vec2(127.1, 311.7)), dot(p, vec2(269.5, 183.3)));
    return -1.0 + 2.0 * fract(sin(p) * 43758.5453123);
  }

  float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(
      mix(dot(hash(i + vec2(0.0, 0.0)), f - vec2(0.0, 0.0)),
          dot(hash(i + vec2(1.0, 0.0)), f - vec2(1.0, 0.0)), u.x),
      mix(dot(hash(i + vec2(0.0, 1.0)), f - vec2(0.0, 1.0)),
          dot(hash(i + vec2(1.0, 1.0)), f - vec2(1.0, 1.0)), u.x),
      u.y
    );
  }

  vec3 hsl2rgb(vec3 c) {
    vec3 rgb = clamp(abs(mod(c.x * 6.0 + vec3(0.0, 4.0, 2.0), 6.0) - 3.0) - 1.0, 0.0, 1.0);
    return c.z + c.y * (rgb - 0.5) * (1.0 - abs(2.0 * c.z - 1.0));
  }

  void main() {
    vec2 uv = vUv;
    // Correct for aspect so the flow does not smear on wide monitors.
    uv.x *= uResolution.x / max(uResolution.y, 1.0);

    float t = uTime * 0.06;

    // Three octaves drifting against each other -- enough to read as organic
    // while staying cheap enough to hold 60fps on integrated graphics.
    float a = noise(uv * 1.1 + vec2(t, t * 0.7));
    float b = noise(uv * 2.3 - vec2(t * 0.8, t * 0.45));
    float c = noise(uv * 4.1 + vec2(t * 0.35, -t * 0.6));
    float field = a * 0.55 + b * 0.3 + c * 0.15;

    // Two soft light sources drifting on their own paths. These are what make
    // it read as a lit volume rather than a noise texture.
    vec2 p = vUv * vec2(uResolution.x / max(uResolution.y, 1.0), 1.0);
    vec2 l1 = vec2(0.28 + sin(t * 1.7) * 0.16, 0.22 + cos(t * 1.3) * 0.12)
              * vec2(uResolution.x / max(uResolution.y, 1.0), 1.0);
    vec2 l2 = vec2(0.78 + cos(t * 1.1) * 0.14, 0.74 + sin(t * 1.9) * 0.13)
              * vec2(uResolution.x / max(uResolution.y, 1.0), 1.0);
    float glow = smoothstep(0.85, 0.0, length(p - l1)) * 0.75
               + smoothstep(0.95, 0.0, length(p - l2)) * 0.55;

    // Keep the centre calmer than the edges so body text holds its contrast,
    // but never fully dark -- a dead centre is what made this invisible.
    vec2 centred = vUv - 0.5;
    float vignette = 0.45 + smoothstep(0.1, 0.9, length(centred)) * 0.55;

    float amount = ((field * 0.5 + 0.5) * 0.55 + glow * 0.75) * uIntensity * vignette;
    amount = clamp(amount, 0.0, 1.0);

    // Hue drifts across the field so it is never a flat wash.
    float hue = uHue / 360.0 + field * 0.045;
    vec3 colour = hsl2rgb(vec3(hue, uSat, 0.56));

    gl_FragColor = vec4(colour * amount, amount);
  }
`;

function FieldPlane() {
  const material = useRef<THREE.ShaderMaterial>(null);
  const { size } = useThree();

  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uIntensity: { value: 0.35 },
      uHue: { value: 250 },
      uSat: { value: 0.6 },
      uResolution: { value: new THREE.Vector2(1, 1) },
    }),
    [],
  );

  useEffect(() => {
    uniforms.uResolution.value.set(size.width, size.height);
  }, [size, uniforms]);

  useFrame((_, delta) => {
    if (!material.current) return;
    const styles = getComputedStyle(document.documentElement);
    const read = (name: string, fallback: number) => {
      const raw = parseFloat(styles.getPropertyValue(name));
      return Number.isFinite(raw) ? raw : fallback;
    };

    const speed = read("--ambient-speed", 1);
    const target = read("--ambient-intensity", 0.35);
    const hue = read("--ambient-hue", 250) + read("--ambient-shift", 0);
    const sat = read("--ambient-sat", 60) / 100;

    uniforms.uTime.value += delta * speed;
    // Ease toward the target so a status change is a swell, not a jump cut.
    uniforms.uIntensity.value += (target - uniforms.uIntensity.value) * Math.min(1, delta * 2);
    uniforms.uHue.value += (hue - uniforms.uHue.value) * Math.min(1, delta * 1.5);
    uniforms.uSat.value = sat;
  });

  return (
    <mesh frustumCulled={false}>
      <planeGeometry args={[2, 2]} />
      <shaderMaterial
        ref={material}
        vertexShader={VERTEX}
        fragmentShader={FRAGMENT}
        uniforms={uniforms}
        transparent
        depthTest={false}
        depthWrite={false}
      />
    </mesh>
  );
}

export default function AmbientField() {
  const { quality } = useAppearance();
  if (!allowsAmbient(quality)) return null;

  return (
    <div
      className="pointer-events-none fixed inset-0 -z-10"
      aria-hidden
      // The shell renders and is interactive regardless; this is decoration and
      // must never be in the accessibility tree or the tab order.
    >
      <Canvas
        gl={{ antialias: false, alpha: true, powerPreference: "low-power" }}
        dpr={[1, 1.5]}
        orthographic
        camera={{ position: [0, 0, 1] }}
      >
        <FieldPlane />
      </Canvas>
    </div>
  );
}
