-- Concepts: Revenues, COGS, GrossProfit, OperatingIncome, R&D, SG&A, D&A,
-- InterestExpense, IncomeTax, NetIncome — full fiscal year durations.
{{ unnest_xbrl_frames('raw', 'raw_income_statement_annual') }}
