# LIHTC sources and uses

`lihtc-sources-uses` sizes federal low-income housing tax credits for one
project and shows whether they, with the other sources, cover the cost. It is
a first look at a deal, not a full tax credit model: it has no credit delivery
schedule, equity pay-ins, construction loan, operations or partnership returns.

## How it works

| Step | Calculation |
|---|---|
| Total development cost | Land plus every cost line |
| Eligible basis | Each cost line times its `basis_fraction`, less `basis_reductions` (federal grants and similar) |
| Applicable fraction | The lower of LIHTC units over total units and LIHTC floor area over total floor area |
| Qualified basis | Eligible basis times (1 + `high_cost_boost`) times the applicable fraction |
| Annual credits | Qualified basis times `credit_rate`. A competitive award (`bond_financed` 0) is capped at `annual_credit_cap`; a bond deal's credits are not capped |
| Tax credit equity | Annual credits times 10 years times `investor_share` times `credit_price` |
| Funding gap | Total development cost less equity, `permanent_loan`, `soft_sources` and `deferred_developer_fee` |

## Inputs to check for every deal

- **`basis_fraction` by cost line.** Land, reserves, syndication costs and
  permanent-loan costs are generally not eligible. Construction interest and
  some soft costs are partly eligible. Use the cost certification or the
  sponsor's accountant's split when you have it.
- **`high_cost_boost`.** Up to 0.30 for a building in a Difficult Development
  Area or Qualified Census Tract, or when the state agency designates it;
  0 otherwise. Check HUD's current DDA and QCT maps and the state's
  qualified allocation plan.
- **`credit_rate`.** 0.04 for a bond-financed deal and 0.09 for a competitive
  award are the fixed minimum rates under current law.
- **`bond_test_threshold`.** The share of aggregate basis (land plus building)
  that tax-exempt bonds must finance for a bond deal's credits: 0.25 for
  bonds issued after 2025 under the 2025 tax law, 0.50 before. Confirm with
  bond counsel. The model approximates aggregate basis as land plus eligible
  basis before reductions.
- **`credit_price` and `investor_share`.** Price per dollar of credit from a
  current investor letter of intent; the investor usually takes 99.99%.

## Checks

- `funded`: sources cover total development cost.
- `basis_supports_allocation`: for a competitive award, qualified basis
  supports the full award.
- `bond_test`: for a bond deal, the bonds meet the required share of aggregate
  basis.

A flagged check does not stop the run; it is a finding to explain.
