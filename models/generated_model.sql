SELECT p.promotion_name,
       COUNT(DISTINCT o.order_id) AS orders_used_promotion
FROM order_entry_db.order_entry.orders o
LEFT JOIN order_entry_db.order_entry.promotions p
    ON o.promotion_id = p.promotion_id
WHERE o.promotion_id IS NOT NULL
GROUP BY p.promotion_name
ORDER BY orders_used_promotion DESC;