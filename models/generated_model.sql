SELECT
    delivery_type,
    SUM(order_total) AS total_order_value,
    AVG(cost_of_delivery) AS avg_delivery_cost
FROM order_entry_db.order_entry.orders
GROUP BY delivery_type
ORDER BY delivery_type;