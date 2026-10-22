/**
 * Editor de tabela 2D (1×N, tuning RF-03, RF-04, RF-10): uma linha de valores sobre o eixo X
 * (ex.: correção por IAT, boost por marcha). Usa os mesmos mecanismos de seleção, operações,
 * undo/redo e heatmap da grade 3D (`TableEditorCore`).
 */
import { TableEditorCore, type TableEditorProps } from "./TableEditorCore";

export function TableEditor2D(props: TableEditorProps) {
  return <TableEditorCore {...props} variant="2d" />;
}
