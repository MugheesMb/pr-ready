select
    pc.category_name,
    sum(oi.quantity * oi.unit_price) as revenue
from {{ source('order_entry', 'order_items') }} oi
left join {{ source('order_entry', 'products') }} p
    on oi.product_id = p.product_id
left join {{ source('order_entry', 'product_categories') }} pc
    on p.category_id = pc.category_id
group by pc.category_name
order by revenue desc