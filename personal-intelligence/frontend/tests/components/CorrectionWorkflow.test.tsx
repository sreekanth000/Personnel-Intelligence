import {
  render,
  screen,
  fireEvent,
  waitFor,
  cleanup,
} from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { CorrectionWorkflow } from "../../src/components/relationship/CorrectionWorkflow";
import { worldApi } from "../../src/api";

vi.mock("../../src/api", () => ({
  worldApi: {
    submitCorrection: vi.fn(),
  },
}));

describe("CorrectionWorkflow", () => {
  const mockOnCorrected = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  it("renders idle buttons initially", () => {
    render(
      <CorrectionWorkflow
        relationshipId="rel1"
        currentSubject="Alice"
        currentPredicate="works_for"
        currentObject="Bob"
        onCorrected={mockOnCorrected}
      />,
    );
    expect(screen.getByText("Confirm")).toBeTruthy();
    expect(screen.getByText("Correct")).toBeTruthy();
    expect(screen.getByText("Reject")).toBeTruthy();
    expect(screen.getByText("Outdated")).toBeTruthy();
  });

  it("shows input fields and reason text area when Correct is clicked", () => {
    render(
      <CorrectionWorkflow
        relationshipId="rel1"
        currentSubject="Alice"
        currentPredicate="works_for"
        currentObject="Bob"
        onCorrected={mockOnCorrected}
      />,
    );

    fireEvent.click(screen.getByText("Correct"));
    expect(screen.getByDisplayValue("Alice")).toBeTruthy();
    expect(screen.getByDisplayValue("works_for")).toBeTruthy();
    expect(screen.getByDisplayValue("Bob")).toBeTruthy();
    expect(
      screen.getByPlaceholderText("Why is this being changed?"),
    ).toBeTruthy();
  });

  it("shows an error if correction reason is empty", async () => {
    render(
      <CorrectionWorkflow
        relationshipId="rel1"
        currentSubject="Alice"
        currentPredicate="works_for"
        currentObject="Bob"
        onCorrected={mockOnCorrected}
      />,
    );

    fireEvent.click(screen.getByText("Correct"));
    fireEvent.click(screen.getByText("Submit"));

    expect(
      screen.getByText("A reason is required for correction."),
    ).toBeTruthy();
    expect(worldApi.submitCorrection).not.toHaveBeenCalled();
  });

  it("submits correction successfully and calls onCorrected", async () => {
    (worldApi.submitCorrection as any).mockResolvedValue({ status: "success" });

    render(
      <CorrectionWorkflow
        relationshipId="rel1"
        currentSubject="Alice"
        currentPredicate="works_for"
        currentObject="Bob"
        onCorrected={mockOnCorrected}
      />,
    );

    fireEvent.click(screen.getByText("Correct"));

    // Fill reason
    fireEvent.change(
      screen.getByPlaceholderText("Why is this being changed?"),
      { target: { value: "Fixed typo" } },
    );

    // Fill new object
    const objectInputs = screen.getAllByDisplayValue("Bob");
    fireEvent.change(objectInputs[0], { target: { value: "Charlie" } });

    fireEvent.click(screen.getByText("Submit"));

    await waitFor(() => {
      expect(worldApi.submitCorrection).toHaveBeenCalledWith(
        "rel1",
        "correct",
        "Fixed typo",
        {
          new_subject: "Alice",
          new_predicate: "works_for",
          new_object: "Charlie",
        },
      );
    });

    await waitFor(() => {
      expect(mockOnCorrected).toHaveBeenCalled();
    });
  });
});
