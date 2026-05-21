-- Concepts: EarningsPerShareBasic, EarningsPerShareDiluted — annual, USD-per-shares.
{{ unnest_xbrl_frames('raw', 'raw_shares_and_eps_annual') }}
