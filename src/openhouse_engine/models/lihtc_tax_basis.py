"""Explicit tax-asset basis adjustments after reviewed project allocations."""
from .. import ref


def declare_tax_basis_adjustment(m, given, *, gross_basis, excluded_basis,
                                 credit_reduction, prefix, dims=()):
    given(prefix + '.retained_fraction', 'ratio', dims, high=1)
    for name, expression in (('gross_basis', gross_basis), ('excluded_basis', excluded_basis),
                             ('credit_reduction', credit_reduction)):
        m.calc(prefix + '.' + name, unit='USD', dims=dims, expr=expression)
        m.check(prefix + '.' + name + '.nonnegative', dims=dims,
                condition=ref(prefix + '.' + name) >= 0, code='INVALID_TAX_BASIS_ADJUSTMENT',
                message='Tax basis amounts and reductions must be nonnegative.')
    m.check(prefix + '.reductions', dims=dims,
            condition=ref(prefix + '.excluded_basis') + ref(prefix + '.credit_reduction') <= ref(prefix + '.gross_basis'),
            code='TAX_BASIS_REDUCTIONS_EXCEED_BASIS',
            message='Tax exclusions and credit reductions exceed the allocated gross asset basis.')
    m.calc(prefix + '.net_basis', unit='USD', dims=dims,
           expr=(ref(prefix + '.gross_basis') - ref(prefix + '.excluded_basis')
                 - ref(prefix + '.credit_reduction')) * ref(prefix + '.retained_fraction'))
