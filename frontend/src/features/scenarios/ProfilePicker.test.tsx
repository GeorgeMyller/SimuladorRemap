import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProfilePicker } from "./ProfilePicker";
import ScenariosPage from "./ScenariosPage";
import { INSTRUCTOR, makeApi, problem, renderWithApi, STUDENT } from "./test-utils/fixtures";
import { ACTIVE_PROFILE_KEY } from "./types";

beforeEach(() => localStorage.clear());

describe("ProfilePicker", () => {
  it("lista os perfis com selo de instrutor e troca o perfil ativo sem senha", async () => {
    renderWithApi(<ProfilePicker />, makeApi());
    const marcos = await screen.findByRole("button", { name: /prof_marcos/ });
    expect(screen.getAllByText("Instrutor").length).toBeGreaterThan(0);
    await userEvent.click(marcos);
    expect(localStorage.getItem(ACTIVE_PROFILE_KEY)).toBe(INSTRUCTOR.profile_id);
    expect(marcos).toHaveAttribute("aria-pressed", "true");
  });

  it("ProfileCreateDialog valida o nickname, cria o perfil e grava simremap.activeProfileId", async () => {
    const created = { ...STUDENT, profile_id: "33333333-3333-4333-8333-333333333333", nickname: "novo_aluno" };
    const createProfile = vi.fn(() => Promise.resolve(created));
    const api = makeApi({ createProfile });
    renderWithApi(<ProfilePicker />, api);
    await userEvent.click(await screen.findByRole("button", { name: "Novo perfil" }));
    const input = screen.getByLabelText("Nickname");
    const submit = screen.getByRole("button", { name: "Criar perfil" });
    await userEvent.type(input, "com espaço");
    expect(submit).toBeDisabled();
    expect(input).toHaveAttribute("aria-invalid", "true");
    await userEvent.clear(input);
    await userEvent.type(input, "a@b");
    expect(submit).toBeDisabled();
    await userEvent.clear(input);
    await userEvent.type(input, "novo_aluno");
    await userEvent.click(screen.getByLabelText("Instrutor"));
    await userEvent.click(submit);
    await waitFor(() => expect(localStorage.getItem(ACTIVE_PROFILE_KEY)).toBe(created.profile_id));
    expect(createProfile).toHaveBeenCalledWith({ nickname: "novo_aluno", role: "instructor" });
  });

  it("mostra NICKNAME_TAKEN do servidor", async () => {
    const api = makeApi({ createProfile: vi.fn(() => Promise.reject(problem(409, "NICKNAME_TAKEN", "já existe"))) });
    renderWithApi(<ProfilePicker />, api);
    await userEvent.click(await screen.findByRole("button", { name: "Novo perfil" }));
    await userEvent.type(screen.getByLabelText("Nickname"), "LUCAS_TURBO");
    await userEvent.click(screen.getByRole("button", { name: "Criar perfil" }));
    expect(await screen.findByText("NICKNAME_TAKEN")).toBeInTheDocument();
  });

  it("ScenariosPage mostra o perfil ativo e o link do painel só para instrutor", async () => {
    localStorage.setItem(ACTIVE_PROFILE_KEY, INSTRUCTOR.profile_id);
    renderWithApi(<ScenariosPage />, makeApi(), "/scenarios/profiles", "/scenarios/*");
    expect(await screen.findByRole("link", { name: "Painel do instrutor" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Perfis desta estação" })).toBeInTheDocument();
  });
});
