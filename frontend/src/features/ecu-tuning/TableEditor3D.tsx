/**
 * Editor de tabela 3D (grade até 32×32, tuning RF-03, RF-04, RF-10, RF-11, RF-12): linhas no
 * eixo Y (carga), colunas no eixo X (rpm), cursor de operação e vista 3D alternável (`F3`).
 */
import { TableEditorCore, type TableEditorProps } from "./TableEditorCore";

export function TableEditor3D(props: TableEditorProps) {
  return <TableEditorCore {...props} variant="3d" />;
}
