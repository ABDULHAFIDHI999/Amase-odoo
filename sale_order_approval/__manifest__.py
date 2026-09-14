# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name': 'Sales Order Approval',
    'version': '19.0.1.0.0',
    'category': 'Sales/Sales',
    'summary': 'Require manager approval before confirming sales orders',
    'description': """
Sales Order Approval
====================
This module adds an approval workflow to sales orders.

When the feature is enabled in Sales settings:
- Salespersons submit quotations for approval instead of confirming directly.
- Sales Managers can approve or refuse the submission.
- Only approved orders proceed to the confirmed (Sales Order) state.
    """,
    'author': 'Odoo Custom',
    'depends': ['sale'],
    'data': [
        'security/res_groups.xml',
        'security/ir.model.access.csv',
        'views/sale_order_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
