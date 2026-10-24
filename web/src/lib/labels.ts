const LABELS: Record<string, string> = {
  date: "Date", value_date: "Value date", description: "Description", ref: "Reference", debit: "Debit",
  credit: "Credit", balance: "Balance", bank_name: "Bank name", account_holder: "Account holder",
  account_number: "Account number", ifsc: "IFSC", branch: "Branch", period_start: "Period start",
  period_end: "Period end", opening_balance: "Opening balance", closing_balance: "Closing balance", currency: "Currency",
};
export const fieldLabel = (field: string): string => LABELS[field] ?? field;
