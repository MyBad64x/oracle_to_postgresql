-- =====================================================================
-- CAMADA DE DECISOES HUMANAS
-- Aplicar DEPOIS da carga dos dados.
-- Este arquivo e escrito a mao e NUNCA e sobrescrito pelo gerador.
-- =====================================================================
-- Ordem de execucao:
--   1. 02_generated_schema.sql (tabelas nuas)
--   2. Secao 1 deste arquivo (correcoes de tipo, antes da carga)
--   3. Carga dos 24 arquivos CSV
--   4. Secoes 2 a 6 deste arquivo (NOT NULL, constraints e indices)

-- ---------------------------------------------------------------------
-- 1. CORRECOES DE TIPO (executar ANTES da carga)
--    Casos onde a inferencia acertou o dado, mas errou o conceito.
-- ---------------------------------------------------------------------

-- Aliquotas: o dataset so tem valores com decimal zerado, mas percentual
-- tributario admite fracao (ex.: 25,5%).
ALTER TABLE order_items      MODIFY (icms_rate NUMBER(5,2));
ALTER TABLE order_items      MODIFY (ipi_rate NUMBER(5,2));
ALTER TABLE product_variants MODIFY (icms_rate NUMBER(5,2));
ALTER TABLE product_variants MODIFY (ipi_rate NUMBER(5,2));

-- Coluna 100% vazia no dataset; o nome indica quantidade de reposicao.
ALTER TABLE stock_levels MODIFY (reorder_point NUMBER(10));

-- ---------------------------------------------------------------------
-- 2. NOT NULL  (baseado na contagem real de vazios nos CSVs)
-- ---------------------------------------------------------------------

ALTER TABLE customers MODIFY (person_type NOT NULL, legal_name NOT NULL, tax_id NOT NULL, is_active NOT NULL, created_at NOT NULL, updated_at NOT NULL);
ALTER TABLE locations MODIFY (name NOT NULL, location_type NOT NULL, postal_code NOT NULL, street NOT NULL, location_number NOT NULL, district NOT NULL, city NOT NULL, state NOT NULL, country NOT NULL, is_active NOT NULL, created_at NOT NULL, updated_at NOT NULL);
ALTER TABLE employees MODIFY (full_name NOT NULL, cpf NOT NULL, email NOT NULL, role NOT NULL, primary_location_id NOT NULL, hire_date NOT NULL, is_active NOT NULL, created_at NOT NULL, updated_at NOT NULL);
ALTER TABLE addresses MODIFY (customer_id NOT NULL, address_type NOT NULL, postal_code NOT NULL, street NOT NULL, address_number NOT NULL, district NOT NULL, city NOT NULL, state NOT NULL, country NOT NULL, is_primary NOT NULL);
ALTER TABLE product_variants MODIFY (product_id NOT NULL, sale_price NOT NULL, cost_price NOT NULL, icms_rate NOT NULL, ipi_rate NOT NULL, is_active NOT NULL, created_at NOT NULL, updated_at NOT NULL);
ALTER TABLE orders MODIFY (order_number NOT NULL, channel NOT NULL, customer_id NOT NULL, status NOT NULL, subtotal NOT NULL, discount_amount NOT NULL, total NOT NULL, placed_at NOT NULL, created_at NOT NULL, updated_at NOT NULL);
ALTER TABLE order_items MODIFY (order_id NOT NULL, product_variant_id NOT NULL, quantity NOT NULL, unit_price NOT NULL, icms_rate NOT NULL, ipi_rate NOT NULL, line_total NOT NULL);

-- ---------------------------------------------------------------------
-- 3. PRIMARY KEYS
-- ---------------------------------------------------------------------

ALTER TABLE customers ADD CONSTRAINT pk_customers PRIMARY KEY (id);
ALTER TABLE locations ADD CONSTRAINT pk_locations PRIMARY KEY (id);
ALTER TABLE employees ADD CONSTRAINT pk_employees PRIMARY KEY (id);
ALTER TABLE addresses ADD CONSTRAINT pk_addresses PRIMARY KEY (id);
ALTER TABLE attributes ADD CONSTRAINT pk_attributes PRIMARY KEY (id);
ALTER TABLE brands ADD CONSTRAINT pk_brands PRIMARY KEY (id);
ALTER TABLE categories ADD CONSTRAINT pk_categories PRIMARY KEY (id);
ALTER TABLE products ADD CONSTRAINT pk_products PRIMARY KEY (id);
ALTER TABLE product_variants ADD CONSTRAINT pk_product_variants PRIMARY KEY (id);
ALTER TABLE suppliers ADD CONSTRAINT pk_suppliers PRIMARY KEY (id);
ALTER TABLE orders ADD CONSTRAINT pk_orders PRIMARY KEY (id);
ALTER TABLE order_items ADD CONSTRAINT pk_order_items PRIMARY KEY (id);
ALTER TABLE payments ADD CONSTRAINT pk_payments PRIMARY KEY (id);
ALTER TABLE fiscal_invoices ADD CONSTRAINT pk_fiscal_invoices PRIMARY KEY (id);
ALTER TABLE purchase_orders ADD CONSTRAINT pk_purchase_orders PRIMARY KEY (id);
ALTER TABLE purchase_order_items ADD CONSTRAINT pk_purchase_order_items PRIMARY KEY (id);
ALTER TABLE goods_receipts ADD CONSTRAINT pk_goods_receipts PRIMARY KEY (id);
ALTER TABLE goods_receipt_items ADD CONSTRAINT pk_goods_receipt_items PRIMARY KEY (id);
ALTER TABLE returns ADD CONSTRAINT pk_returns PRIMARY KEY (id);
ALTER TABLE return_items ADD CONSTRAINT pk_return_items PRIMARY KEY (id);
ALTER TABLE stock_movements ADD CONSTRAINT pk_stock_movements PRIMARY KEY (id);
ALTER TABLE product_suppliers ADD CONSTRAINT pk_product_suppliers PRIMARY KEY (product_variant_id, supplier_id);
ALTER TABLE stock_levels ADD CONSTRAINT pk_stock_levels PRIMARY KEY (product_variant_id, location_id);
ALTER TABLE variant_attribute_values ADD CONSTRAINT pk_variant_attribute_values PRIMARY KEY (product_variant_id, attribute_id);

-- ---------------------------------------------------------------------
-- 4. CHECK CONSTRAINTS  (dominios confirmados com Counter)
-- ---------------------------------------------------------------------

ALTER TABLE customers ADD CONSTRAINT chk_customers_person_type CHECK (person_type IN ('PF', 'PJ'));
ALTER TABLE customers ADD CONSTRAINT chk_customers_is_active CHECK (is_active IN (0, 1));
ALTER TABLE locations ADD CONSTRAINT chk_locations_location_type CHECK (location_type IN ('store', 'warehouse'));
ALTER TABLE locations ADD CONSTRAINT chk_locations_is_active CHECK (is_active IN (0, 1));
ALTER TABLE employees ADD CONSTRAINT chk_employees_is_active CHECK (is_active IN (0, 1));
ALTER TABLE addresses ADD CONSTRAINT chk_addresses_address_type CHECK (address_type IN ('billing', 'secondary'));
ALTER TABLE addresses ADD CONSTRAINT chk_addresses_is_primary CHECK (is_primary IN (0, 1));
ALTER TABLE product_variants ADD CONSTRAINT chk_product_variants_is_active CHECK (is_active IN (0, 1));
ALTER TABLE orders ADD CONSTRAINT chk_orders_channel CHECK (channel IN ('ecommerce', 'pos'));
ALTER TABLE orders ADD CONSTRAINT chk_orders_status CHECK (status IN ('paid', 'confirmed', 'cancelled', 'draft'));
ALTER TABLE order_items ADD CONSTRAINT chk_order_items_quantity CHECK (quantity > 0);

-- ---------------------------------------------------------------------
-- 5. FOREIGN KEYS
-- ---------------------------------------------------------------------

ALTER TABLE employees ADD CONSTRAINT fk_employees_locations FOREIGN KEY (primary_location_id) REFERENCES locations(id);
ALTER TABLE addresses ADD CONSTRAINT fk_addresses_customers FOREIGN KEY (customer_id) REFERENCES customers(id);
ALTER TABLE categories ADD CONSTRAINT fk_categories_parent FOREIGN KEY (parent_category_id) REFERENCES categories(id);
ALTER TABLE products ADD CONSTRAINT fk_products_brands FOREIGN KEY (brand_id) REFERENCES brands(id);
ALTER TABLE products ADD CONSTRAINT fk_products_categories FOREIGN KEY (category_id) REFERENCES categories(id);
ALTER TABLE product_variants ADD CONSTRAINT fk_product_variants_products FOREIGN KEY (product_id) REFERENCES products(id);
ALTER TABLE product_suppliers ADD CONSTRAINT fk_product_suppliers_variants FOREIGN KEY (product_variant_id) REFERENCES product_variants(id);
ALTER TABLE product_suppliers ADD CONSTRAINT fk_product_suppliers_suppliers FOREIGN KEY (supplier_id) REFERENCES suppliers(id);
ALTER TABLE orders ADD CONSTRAINT fk_orders_customers FOREIGN KEY (customer_id) REFERENCES customers(id);
ALTER TABLE orders ADD CONSTRAINT fk_orders_employees FOREIGN KEY (salesperson_id) REFERENCES employees(id);
ALTER TABLE orders ADD CONSTRAINT fk_orders_locations FOREIGN KEY (location_id) REFERENCES locations(id);
ALTER TABLE order_items ADD CONSTRAINT fk_order_items_orders FOREIGN KEY (order_id) REFERENCES orders(id);
ALTER TABLE order_items ADD CONSTRAINT fk_order_items_variants FOREIGN KEY (product_variant_id) REFERENCES product_variants(id);
ALTER TABLE payments ADD CONSTRAINT fk_payments_orders FOREIGN KEY (order_id) REFERENCES orders(id);
ALTER TABLE fiscal_invoices ADD CONSTRAINT fk_fiscal_invoices_orders FOREIGN KEY (order_id) REFERENCES orders(id);
ALTER TABLE purchase_orders ADD CONSTRAINT fk_purchase_orders_suppliers FOREIGN KEY (supplier_id) REFERENCES suppliers(id);
ALTER TABLE purchase_orders ADD CONSTRAINT fk_purchase_orders_buyers FOREIGN KEY (buyer_id) REFERENCES employees(id);
ALTER TABLE purchase_orders ADD CONSTRAINT fk_purchase_orders_locations FOREIGN KEY (destination_location_id) REFERENCES locations(id);
ALTER TABLE purchase_order_items ADD CONSTRAINT fk_purchase_order_items_orders FOREIGN KEY (purchase_order_id) REFERENCES purchase_orders(id);
ALTER TABLE purchase_order_items ADD CONSTRAINT fk_purchase_order_items_variants FOREIGN KEY (product_variant_id) REFERENCES product_variants(id);
ALTER TABLE goods_receipts ADD CONSTRAINT fk_goods_receipts_orders FOREIGN KEY (purchase_order_id) REFERENCES purchase_orders(id);
ALTER TABLE goods_receipts ADD CONSTRAINT fk_goods_receipts_employees FOREIGN KEY (received_by_employee_id) REFERENCES employees(id);
ALTER TABLE goods_receipt_items ADD CONSTRAINT fk_goods_receipt_items_receipts FOREIGN KEY (goods_receipt_id) REFERENCES goods_receipts(id);
ALTER TABLE goods_receipt_items ADD CONSTRAINT fk_goods_receipt_items_po_items FOREIGN KEY (purchase_order_item_id) REFERENCES purchase_order_items(id);
ALTER TABLE returns ADD CONSTRAINT fk_returns_orders FOREIGN KEY (order_id) REFERENCES orders(id);
ALTER TABLE returns ADD CONSTRAINT fk_returns_customers FOREIGN KEY (customer_id) REFERENCES customers(id);
ALTER TABLE returns ADD CONSTRAINT fk_returns_locations FOREIGN KEY (received_at_location_id) REFERENCES locations(id);
ALTER TABLE return_items ADD CONSTRAINT fk_return_items_returns FOREIGN KEY (return_id) REFERENCES returns(id);
ALTER TABLE return_items ADD CONSTRAINT fk_return_items_order_items FOREIGN KEY (order_item_id) REFERENCES order_items(id);
ALTER TABLE return_items ADD CONSTRAINT fk_return_items_variants FOREIGN KEY (exchange_variant_id) REFERENCES product_variants(id);
ALTER TABLE stock_levels ADD CONSTRAINT fk_stock_levels_variants FOREIGN KEY (product_variant_id) REFERENCES product_variants(id);
ALTER TABLE stock_levels ADD CONSTRAINT fk_stock_levels_locations FOREIGN KEY (location_id) REFERENCES locations(id);
ALTER TABLE stock_movements ADD CONSTRAINT fk_stock_movements_variants FOREIGN KEY (product_variant_id) REFERENCES product_variants(id);
ALTER TABLE stock_movements ADD CONSTRAINT fk_stock_movements_locations FOREIGN KEY (location_id) REFERENCES locations(id);
ALTER TABLE stock_movements ADD CONSTRAINT fk_stock_movements_employees FOREIGN KEY (employee_id) REFERENCES employees(id);
ALTER TABLE variant_attribute_values ADD CONSTRAINT fk_variant_attribute_values_variants FOREIGN KEY (product_variant_id) REFERENCES product_variants(id);
ALTER TABLE variant_attribute_values ADD CONSTRAINT fk_variant_attribute_values_attributes FOREIGN KEY (attribute_id) REFERENCES attributes(id);

-- ---------------------------------------------------------------------
-- 6. INDICES  (toda FK precisa de um — ver nota sobre lock de tabela)
-- ---------------------------------------------------------------------

CREATE INDEX idx_customers_tax_id ON customers (tax_id);
CREATE INDEX idx_employees_primary_location_id ON employees (primary_location_id);
CREATE INDEX idx_employees_cpf ON employees (cpf);
CREATE INDEX idx_addresses_customer_id ON addresses (customer_id);
CREATE INDEX idx_categories_parent_category_id ON categories (parent_category_id);
CREATE INDEX idx_products_brand_id ON products (brand_id);
CREATE INDEX idx_products_category_id ON products (category_id);
CREATE INDEX idx_product_variants_product_id ON product_variants (product_id);
CREATE INDEX idx_product_suppliers_supplier_id ON product_suppliers (supplier_id);
CREATE INDEX idx_orders_customer_id ON orders (customer_id);
CREATE INDEX idx_orders_salesperson_id ON orders (salesperson_id);
CREATE INDEX idx_orders_location_id ON orders (location_id);
CREATE INDEX idx_order_items_order_id ON order_items (order_id);
CREATE INDEX idx_order_items_product_variant_id ON order_items (product_variant_id);
CREATE INDEX idx_payments_order_id ON payments (order_id);
CREATE INDEX idx_fiscal_invoices_order_id ON fiscal_invoices (order_id);
CREATE INDEX idx_purchase_orders_supplier_id ON purchase_orders (supplier_id);
CREATE INDEX idx_purchase_orders_buyer_id ON purchase_orders (buyer_id);
CREATE INDEX idx_purchase_orders_destination_location_id ON purchase_orders (destination_location_id);
CREATE INDEX idx_purchase_order_items_purchase_order_id ON purchase_order_items (purchase_order_id);
CREATE INDEX idx_purchase_order_items_product_variant_id ON purchase_order_items (product_variant_id);
CREATE INDEX idx_goods_receipts_purchase_order_id ON goods_receipts (purchase_order_id);
CREATE INDEX idx_goods_receipts_received_by_employee_id ON goods_receipts (received_by_employee_id);
CREATE INDEX idx_goods_receipt_items_goods_receipt_id ON goods_receipt_items (goods_receipt_id);
CREATE INDEX idx_goods_receipt_items_purchase_order_item_id ON goods_receipt_items (purchase_order_item_id);
CREATE INDEX idx_returns_order_id ON returns (order_id);
CREATE INDEX idx_returns_customer_id ON returns (customer_id);
CREATE INDEX idx_returns_received_at_location_id ON returns (received_at_location_id);
CREATE INDEX idx_return_items_return_id ON return_items (return_id);
CREATE INDEX idx_return_items_order_item_id ON return_items (order_item_id);
CREATE INDEX idx_return_items_exchange_variant_id ON return_items (exchange_variant_id);
CREATE INDEX idx_stock_levels_location_id ON stock_levels (location_id);
CREATE INDEX idx_stock_movements_variant_id ON stock_movements (product_variant_id);
CREATE INDEX idx_stock_movements_location_id ON stock_movements (location_id);
CREATE INDEX idx_stock_movements_employee_id ON stock_movements (employee_id);
CREATE INDEX idx_variant_attribute_values_attribute_id ON variant_attribute_values (attribute_id);
