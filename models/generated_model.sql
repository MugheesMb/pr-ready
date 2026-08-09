WITH order_status_mapped AS (
    SELECT
        order_id,
        order_total,
        CASE order_status
            WHEN 1 THEN 'Pending'
            WHEN 2 THEN 'Processing'
            WHEN 3 THEN 'Shipped'
            ELSE 'Unknown'
        END AS order_status
    FROM order_entry_db.order_entry.orders
)
SELECT
    order_status,
    COUNT(order_id) AS total_orders,
    AVG(order_total) AS avg_order_value
FROM order_status_mapped
GROUP BY order_status
ORDER BY order_status