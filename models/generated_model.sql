SELECT
    pc.category_id,
    pc.category_name,
    SUM(oi.unit_price * oi.quantity) AS revenue
FROM {{ source('order_entry', 'order_items') }} oi
INNER JOIN {{ source('order_entry', 'products') }} p
    ON oi.product_id = p.product_id
INNER JOIN {{ source('order_entry', 'product_categories') }} pc
    ON p.category_id = pc.category_id
GROUP BY pc.category_id, pc.category_name
ORDER BY revenue DESC