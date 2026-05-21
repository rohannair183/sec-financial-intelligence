-- Concepts: Assets, Liabilities, StockholdersEquity, Cash, LongTermDebt,
-- RetainedEarnings, AccountsReceivable, Inventory, Goodwill — quarterly instants.
{{ unnest_xbrl_frames('raw', 'raw_balance_sheet_snapshots') }}
