/** Represents a stable domain failure that can cross application boundaries. */
export class DomainError extends Error {
  public constructor(
    public readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "DomainError";
  }
}
