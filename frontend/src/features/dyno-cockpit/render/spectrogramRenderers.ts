/**
 * Renderizadores do espectrograma (D-22): textura WebGL com shader de mapa de cores, que
 * desloca a janela por `uniform` sem copiar `ImageData`; fallback Canvas 2D deslocando 1 coluna.
 */
import type { Surface } from "./createSurface";
import { heatColor, SpectrogramModel } from "./SpectrogramModel";

export interface SpectrogramRenderer {
  /** Grava a coluna mais recente do modelo e desenha. */
  update(model: SpectrogramModel): void;
  /** Redesenha a janela inteira (após restauração de contexto ou resize). */
  redrawAll(model: SpectrogramModel): void;
  dispose(): void;
}

const VERT = `
attribute vec2 a_pos;
varying vec2 v_uv;
void main() {
  v_uv = (a_pos + 1.0) * 0.5;
  gl_Position = vec4(a_pos, 0.0, 1.0);
}`;

// x = tempo (coluna no anel, deslocada por u_head), y = frequência (bin).
const FRAG = `
precision mediump float;
varying vec2 v_uv;
uniform sampler2D u_tex;
uniform float u_head;
uniform float u_cols;
vec3 heat(float x) {
  vec3 c0 = vec3(0.0, 0.0, 0.016);
  vec3 c1 = vec3(0.341, 0.063, 0.431);
  vec3 c2 = vec3(0.737, 0.216, 0.329);
  vec3 c3 = vec3(0.976, 0.557, 0.035);
  vec3 c4 = vec3(0.988, 1.0, 0.643);
  float t = clamp(x, 0.0, 1.0) * 4.0;
  if (t < 1.0) return mix(c0, c1, t);
  if (t < 2.0) return mix(c1, c2, t - 1.0);
  if (t < 3.0) return mix(c2, c3, t - 2.0);
  return mix(c3, c4, t - 3.0);
}
void main() {
  float col = fract((v_uv.x * u_cols + u_head) / u_cols);
  float v = texture2D(u_tex, vec2(v_uv.y, col)).r;
  gl_FragColor = vec4(heat(v), 1.0);
}`;

type GL = WebGLRenderingContext | WebGL2RenderingContext;

function compile(gl: GL, type: number, src: string): WebGLShader {
  const shader = gl.createShader(type);
  if (!shader) throw new Error("createShader falhou");
  gl.shaderSource(shader, src);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    const log = gl.getShaderInfoLog(shader);
    gl.deleteShader(shader);
    throw new Error(`shader inválido: ${log ?? ""}`);
  }
  return shader;
}

export function createWebGLRenderer(gl: GL, model: SpectrogramModel): SpectrogramRenderer {
  const program = gl.createProgram();
  if (!program) throw new Error("createProgram falhou");
  gl.attachShader(program, compile(gl, gl.VERTEX_SHADER, VERT));
  gl.attachShader(program, compile(gl, gl.FRAGMENT_SHADER, FRAG));
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error("link do programa falhou");
  gl.useProgram(program);

  const buf = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(program, "a_pos");
  gl.enableVertexAttribArray(loc);
  gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);

  // Textura bins (largura) × colunas (altura), 1 byte por célula (LUMINANCE, compatível com WebGL1).
  const tex = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, tex);
  gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.LUMINANCE, model.bins, model.columns, 0, gl.LUMINANCE, gl.UNSIGNED_BYTE, new Uint8Array(model.bins * model.columns));

  const uHead = gl.getUniformLocation(program, "u_head");
  const uCols = gl.getUniformLocation(program, "u_cols");
  gl.uniform1f(uCols, model.columns);

  const draw = (m: SpectrogramModel) => {
    gl.viewport(0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight);
    gl.uniform1f(uHead, m.head);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  };

  return {
    update(m) {
      if (m.filled === 0) return;
      gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, m.latestColumn(), m.bins, 1, gl.LUMINANCE, gl.UNSIGNED_BYTE, m.latestColumnBytes());
      draw(m);
    },
    redrawAll(m) {
      const all = new Uint8Array(m.bins * m.columns);
      for (let i = 0; i < all.length; i += 1) all[i] = Math.round(SpectrogramModel.normalize(m.data[i]!) * 255);
      gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, m.bins, m.columns, gl.LUMINANCE, gl.UNSIGNED_BYTE, all);
      draw(m);
    },
    dispose() {
      gl.deleteTexture(tex);
      gl.deleteBuffer(buf);
      gl.deleteProgram(program);
    },
  };
}

/** Fallback Canvas 2D: desloca a imagem 1 coluna à esquerda e pinta a coluna nova à direita. */
export function createCanvas2DRenderer(ctx: CanvasRenderingContext2D, canvas: HTMLCanvasElement): SpectrogramRenderer {
  const paintColumn = (m: SpectrogramModel, physical: number, x: number, colWidth: number) => {
    const h = canvas.height;
    const img = ctx.createImageData(Math.max(1, Math.ceil(colWidth)), h);
    const col = m.column(physical);
    for (let y = 0; y < h; y += 1) {
      // y = 0 no topo ⇒ 20 kHz; base ⇒ 0 Hz.
      const bin = Math.min(m.bins - 1, Math.floor(((h - 1 - y) / h) * m.bins));
      const [r, g, b] = heatColor(SpectrogramModel.normalize(col[bin]!));
      for (let dx = 0; dx < img.width; dx += 1) {
        const o = (y * img.width + dx) * 4;
        img.data[o] = r;
        img.data[o + 1] = g;
        img.data[o + 2] = b;
        img.data[o + 3] = 255;
      }
    }
    ctx.putImageData(img, Math.floor(x), 0);
  };
  return {
    update(m) {
      if (m.filled === 0) return;
      const colWidth = canvas.width / m.columns;
      const shift = Math.max(1, Math.round(colWidth));
      ctx.drawImage(canvas, -shift, 0);
      paintColumn(m, m.latestColumn(), canvas.width - shift, shift);
    },
    redrawAll(m) {
      const colWidth = canvas.width / m.columns;
      for (let i = 0; i < m.columns; i += 1) {
        const physical = (m.head + i) % m.columns;
        paintColumn(m, physical, i * colWidth, colWidth);
      }
    },
    dispose() {
      /* nada a libertar */
    },
  };
}

/** Escolhe o renderizador pela superfície; WebGL que falha a compilar cai para 2D. */
export function createSpectrogramRenderer(
  surface: Surface,
  model: SpectrogramModel,
  fallback2d: () => CanvasRenderingContext2D | null,
): { renderer: SpectrogramRenderer | null; kind: Surface["kind"] } {
  if (surface.kind === "webgl2" || surface.kind === "webgl") {
    try {
      return { renderer: createWebGLRenderer(surface.gl, model), kind: surface.kind };
    } catch {
      const ctx = fallback2d();
      return ctx ? { renderer: createCanvas2DRenderer(ctx, surface.canvas), kind: "2d" } : { renderer: null, kind: "none" };
    }
  }
  if (surface.kind === "2d") return { renderer: createCanvas2DRenderer(surface.ctx, surface.canvas), kind: "2d" };
  return { renderer: null, kind: "none" };
}
