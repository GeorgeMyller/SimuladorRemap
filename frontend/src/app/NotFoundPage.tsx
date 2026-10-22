import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <section className="py-16 text-center">
      <h1 className="text-2xl font-semibold">Página não encontrada</h1>
      <Link to="/" className="mt-4 inline-block text-amber-400 underline">
        Voltar ao início
      </Link>
    </section>
  );
}
