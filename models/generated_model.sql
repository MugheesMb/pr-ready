SELECT
    p.promotion_id,
    p.promotion_name,
    COUNT(DISTINCT o.order_id) AS order_count
FROM order_entry_db.order_entry.orders o
LEFT JOIN order_entry_db.order_entry.promotions p
    ON o.promotion_id = p.promotion_id
GROUP BY
    p.promotion_id,
    p.promotion_name
ORDER BY
    order_count DESC