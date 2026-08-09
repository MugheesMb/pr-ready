SELECT
  pc.category_name,
  SUM(oi.quantity * oi.unit_price) AS revenue
FROM {{ ref('order_items') }} AS oi
JOIN {{ ref('products') }} AS p
  ON oi.product_id = p.product_id
JOIN {{ ref('product_categories') }} AS pc
  ON p.category_id = pc.category_id
GROUP BY pc.category_name
ORDER BY revenue DESC;