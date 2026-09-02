-- DESTRUCTIVE TEST-ENVIRONMENT SCRIPT.
-- Deletes all order-domain data in child-to-parent order. Never configure this
-- file for production use or automatic execution during normal application startup.

DELETE FROM demo_payment_callback;
DELETE FROM demo_payment;
DELETE FROM demo_order_item;
DELETE FROM demo_order;
DELETE FROM demo_user_coupon;
DELETE FROM demo_inventory;
DELETE FROM demo_coupon;
DELETE FROM demo_product;
DELETE FROM demo_user;
