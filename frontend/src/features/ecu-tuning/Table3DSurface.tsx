/**
 * Superfície WebGL rotacionável da tabela (tuning RF-12, RNF-03; D-22). Carregada só em chunk
 * lazy por `Table3DView` (three.js nunca entra no bundle inicial). Arrastar = orbitar,
 * roda = zoom, duplo clique = repor. A célula ativa da grade fica destacada no vértice.
 */
import { useEffect, useRef } from "react";
import {
  BufferAttribute,
  BufferGeometry,
  Color,
  Mesh,
  MeshBasicMaterial,
  PerspectiveCamera,
  Scene,
  SphereGeometry,
  WebGLRenderer,
  WireframeGeometry,
  LineSegments,
  LineBasicMaterial,
  DoubleSide,
} from "three";

import { buildSurface, vertexIndex } from "./Table3DGeometry";

export interface Table3DSurfaceProps {
  values: number[][];
  focus: { row: number; col: number };
  /** Contexto perdido ou criação falhou: o pai mostra o contorno 2D. */
  onFallback: () => void;
  width?: number;
  height?: number;
}

const DEFAULT_ORBIT = { theta: Math.PI / 4, phi: Math.PI / 3.2, radius: 3.6 };

export default function Table3DSurface({ values, focus, onFallback, width = 480, height = 320 }: Table3DSurfaceProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const ctx = useRef<{
    renderer: WebGLRenderer;
    scene: Scene;
    camera: PerspectiveCamera;
    mesh: Mesh;
    wire: LineSegments;
    marker: Mesh;
    orbit: { theta: number; phi: number; radius: number };
    render: () => void;
  } | null>(null);
  const fallbackRef = useRef(onFallback);
  useEffect(() => {
    fallbackRef.current = onFallback;
  });

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    let renderer: WebGLRenderer;
    try {
      renderer = new WebGLRenderer({ antialias: true });
    } catch {
      fallbackRef.current();
      return;
    }
    renderer.setSize(width, height);
    renderer.setClearColor(new Color("#09090b"));
    host.appendChild(renderer.domElement);
    const scene = new Scene();
    const camera = new PerspectiveCamera(45, width / height, 0.1, 100);
    const mesh = new Mesh(new BufferGeometry(), new MeshBasicMaterial({ vertexColors: true, side: DoubleSide }));
    const wire = new LineSegments(new BufferGeometry(), new LineBasicMaterial({ color: 0x18181b, transparent: true, opacity: 0.5 }));
    const marker = new Mesh(new SphereGeometry(0.04, 12, 12), new MeshBasicMaterial({ color: 0xf59e0b }));
    scene.add(mesh, wire, marker);
    const orbit = { ...DEFAULT_ORBIT };
    const render = () => {
      const { theta, phi, radius } = orbit;
      camera.position.set(radius * Math.sin(phi) * Math.cos(theta), radius * Math.cos(phi) + 0.4, radius * Math.sin(phi) * Math.sin(theta));
      camera.lookAt(0, 0.4, 0);
      renderer.render(scene, camera);
    };
    ctx.current = { renderer, scene, camera, mesh, wire, marker, orbit, render };

    const canvas = renderer.domElement;
    canvas.setAttribute("aria-hidden", "true");
    let drag: { x: number; y: number } | null = null;
    const onDown = (e: PointerEvent) => {
      drag = { x: e.clientX, y: e.clientY };
    };
    const onMove = (e: PointerEvent) => {
      if (!drag) return;
      orbit.theta += (e.clientX - drag.x) * 0.01;
      orbit.phi = Math.min(Math.PI / 2 - 0.05, Math.max(0.15, orbit.phi - (e.clientY - drag.y) * 0.01));
      drag = { x: e.clientX, y: e.clientY };
      render();
    };
    const onUp = () => {
      drag = null;
    };
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      orbit.radius = Math.min(10, Math.max(1.5, orbit.radius * (e.deltaY > 0 ? 1.1 : 0.9)));
      render();
    };
    const onDbl = () => {
      Object.assign(orbit, DEFAULT_ORBIT);
      render();
    };
    const onLost = (e: Event) => {
      e.preventDefault();
      fallbackRef.current();
    };
    canvas.addEventListener("pointerdown", onDown);
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    canvas.addEventListener("wheel", onWheel, { passive: false });
    canvas.addEventListener("dblclick", onDbl);
    canvas.addEventListener("webglcontextlost", onLost);
    return () => {
      canvas.removeEventListener("pointerdown", onDown);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      canvas.removeEventListener("wheel", onWheel);
      canvas.removeEventListener("dblclick", onDbl);
      canvas.removeEventListener("webglcontextlost", onLost);
      mesh.geometry.dispose();
      wire.geometry.dispose();
      marker.geometry.dispose();
      renderer.dispose();
      canvas.remove();
      ctx.current = null;
    };
  }, [width, height]);

  useEffect(() => {
    const c = ctx.current;
    if (!c) return;
    const data = buildSurface(values);
    const geom = new BufferGeometry();
    geom.setAttribute("position", new BufferAttribute(data.positions, 3));
    geom.setAttribute("color", new BufferAttribute(data.colors, 3));
    geom.setIndex(new BufferAttribute(data.indices, 1));
    c.mesh.geometry.dispose();
    c.mesh.geometry = geom;
    c.wire.geometry.dispose();
    c.wire.geometry = new WireframeGeometry(geom);
    const k = vertexIndex(focus.row, focus.col, data.nx) * 3;
    c.marker.position.set(data.positions[k] ?? 0, (data.positions[k + 1] ?? 0) + 0.02, data.positions[k + 2] ?? 0);
    c.render();
  }, [values, focus.row, focus.col]);

  return <div ref={hostRef} data-testid="table3d-surface" data-highlight={`${focus.row},${focus.col}`} style={{ width, height }} />;
}
