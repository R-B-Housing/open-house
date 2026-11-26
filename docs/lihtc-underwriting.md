# LIHTC underwriting

Use **acquisition/rehab** for an existing property with dated rehabilitation
costs, financing and credit equity. Use **new construction** to size a
ground-up California 4% bond and state-credit deal.

## Start with a synthetic deal

After [installing Open House](../README.md#manual-setup), activate its Python
environment and run the commands for the deal type you want to explore.

```sh
python underwrite.py new lihtc-acquisition-rehab deals/rehab/model.json
python underwrite.py run deals/rehab/model.json

python underwrite.py new lihtc-new-construction deals/construction/model.json
python underwrite.py run deals/construction/model.json
```

Open the resulting `model.xlsx` on **Summary**. The blue cells on the input
sheets recalculate the workbook when changed. Use the **Checks** sheet to
review validation. Excel edits stay in that workbook. To preserve assumptions
for future runs, make your changes in the JSON file and generate a workbook
for each scenario.

## Acquisition and rehab

Set the acquisition date, forecast length, conversion month, cost lines,
unit types, loans, equity installments and tax assets in `deal.structure`.
Set amounts and rates in `inputs`. The monthly forecast covers development
costs, construction draws and interest, permanent debt, operating cash,
reserves and partner distributions. Tax allocations, credits and the
optional investor buyout feed investor returns.

A cash shortfall can occur even when final cash is positive. Review
`funding.maximum_gap` and `funding.shortfall_months` alongside the monthly
cash schedule. Record actual funding commitments and draw dates explicitly.
For an investor buyout, enter reviewed outside basis, liability relief and
tax rates. The model uses these inputs to estimate sale taxes. Tax credit
recapture and automatic outside-basis rollforwards are outside its scope.

## New construction

Start with development costs, a unit mix, rent and utility limits, and the
stabilized operating budget. Enter federal and state credit rates, limits and
pricing, plus permanent and soft loan terms. The model sizes permanent debt
from DSCR and reports annual cash flow, deferred fee payments and residual
receipts. Review the signed permanent sources surplus or shortfall,
construction sources, bond test and California threshold basis limit. The
California rules and annual cash-flow schedule suit 4% bond underwriting.
Use current program limits and financing terms for the project.

## Edit, check and compare

`inputs FILE` lists each input with its unit and bounds. Use `find FILE TEXT`
to locate variables and `values FILE NAME` to inspect their results.
Use exact decimal strings, such as `"0.055"` for 5.5%. Dimensioned inputs
are arrays of indexed rows. A range repeats the value for every integer
from `start` through `end`, inclusive. For example, this provides a monthly
input with $800,000 at month zero and zero in months 1–180.

```json
[
  {"index": [0], "value": "800000"},
  {"index": [{"start": 1, "end": 180}], "value": "0"}
]
```

Each required index needs exactly one value. Change the indexed rows when
you change the structure. Record assumption sources in the JSON file following
[the agent guide](../AGENTS.md). Copy the file before changing a scenario and
run `check` on both cases to compare the headline figures. Run `run` to write
their workbooks.
