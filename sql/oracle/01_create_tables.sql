CREATE TABLE customers (
    id NUMBER(10) NOT NULL,
    person_type VARCHAR2(2) NOT NULL,
    legal_name VARCHAR2(200) NOT NULL,
    trade_name VARCHAR2(200),
    tax_id VARCHAR2(20) NOT NULL,
    state_registration VARCHAR2(50),
    email VARCHAR2(255),
    phone VARCHAR2(20),
    is_active NUMBER(1) NOT NULL,
    created_at DATE NOT NULL,
    updated_at DATE NOT NULL,

    CONSTRAINT pk_customers PRIMARY KEY (id),
    CONSTRAINT chk_customers_person_type CHECK (person_type IN ('PF', 'PJ')),
    CONSTRAINT chk_customers_is_active CHECK (is_active IN (0, 1))
);

CREATE INDEX idx_customers_tax_id ON customers (tax_id);

CREATE TABLE locations (
    id NUMBER(10) NOT NULL,
    name VARCHAR2(200) NOT NULL,
    location_type VARCHAR2(20) NOT NULL,
    postal_code VARCHAR2(20) NOT NULL,
    street VARCHAR2(200) NOT NULL,
    street_number VARCHAR2(20) NOT NULL,
    complement VARCHAR2(200),
    district VARCHAR2(100) NOT NULL,
    city VARCHAR2(100) NOT NULL,
    state VARCHAR2(2) NOT NULL,
    country VARCHAR2(2) NOT NULL,
    is_active NUMBER(1) NOT NULL,
    created_at DATE NOT NULL,
    updated_at DATE NOT NULL,

    CONSTRAINT pk_locations PRIMARY KEY (id),
    CONSTRAINT chk_locations_location_type CHECK (location_type IN ('store', 'warehouse')),
    CONSTRAINT chk_locations_is_active CHECK (is_active IN (0, 1))
);

CREATE TABLE employees (
    id NUMBER(10) NOT NULL,
    full_name VARCHAR2(200) NOT NULL,
    cpf VARCHAR2(14) NOT NULL,
    email VARCHAR2(255) NOT NULL,
    role VARCHAR2(50) NOT NULL,
    primary_location_id NUMBER(10) NOT NULL,
    hire_date DATE NOT NULL,
    termination_date DATE,
    is_active NUMBER(1) NOT NULL,
    created_at DATE NOT NULL,
    updated_at DATE NOT NULL,

    CONSTRAINT pk_employees PRIMARY KEY (id),
    CONSTRAINT chk_employees_is_active CHECK (is_active IN (0, 1))
);

CREATE INDEX idx_employees_cpf ON employees (cpf);

CREATE TABLE addresses (
    id NUMBER(10) NOT NULL,
    customer_id NUMBER(10) NOT NULL,
    address_type VARCHAR2(20) NOT NULL,
    postal_code VARCHAR2(20) NOT NULL,
    street VARCHAR2(200) NOT NULL,
    street_number VARCHAR2(20) NOT NULL,
    complement VARCHAR2(200),
    district VARCHAR2(100) NOT NULL,
    city VARCHAR2(100) NOT NULL,
    state VARCHAR2(2) NOT NULL,
    country VARCHAR2(2) NOT NULL,
    is_primary NUMBER(1) NOT NULL,

    CONSTRAINT pk_addresses PRIMARY KEY (id),
    CONSTRAINT chk_addresses_address_type CHECK (address_type IN ('billing', 'secondary')),
    CONSTRAINT chk_addresses_is_primary CHECK (is_primary IN (0, 1))
);

CREATE INDEX idx_addresses_customer_id ON addresses (customer_id);

CREATE TABLE product_variants (
    id NUMBER(10) NOT NULL,
    product_id NUMBER(10) NOT NULL,
    sku VARCHAR2(50),
    barcode_ean VARCHAR2(50),
    sale_price NUMBER(12,2) NOT NULL,
    cost_price NUMBER(12,2) NOT NULL,
    weight_kg NUMBER(10,3),
    icms_rate NUMBER(5,2) NOT NULL,
    ipi_rate NUMBER(5,2) NOT NULL,
    is_active NUMBER(1) NOT NULL,
    created_at DATE NOT NULL,
    updated_at DATE NOT NULL,

    CONSTRAINT pk_product_variants PRIMARY KEY (id),
    CONSTRAINT chk_product_variants_is_active CHECK (is_active IN (0, 1))
);

-- TODO: quando a tabela products for criada, incluir a FK product_variants.product_id
-- em bloco final, junto com as demais constraints de relacionamento.
CREATE INDEX idx_product_variants_product_id ON product_variants (product_id);

CREATE TABLE orders (
    id NUMBER(10) NOT NULL,
    order_number VARCHAR2(50) NOT NULL,
    channel VARCHAR2(20) NOT NULL,
    customer_id NUMBER(10) NOT NULL,
    salesperson_id NUMBER(10),
    location_id NUMBER(10),
    status VARCHAR2(30) NOT NULL,
    subtotal NUMBER(12,2) NOT NULL,
    discount_amount NUMBER(12,2) NOT NULL,
    total NUMBER(12,2) NOT NULL,
    placed_at DATE NOT NULL,
    created_at DATE NOT NULL,
    updated_at DATE NOT NULL,

    CONSTRAINT pk_orders PRIMARY KEY (id),
    CONSTRAINT chk_orders_channel CHECK (channel IN ('ecommerce', 'pos')),
    CONSTRAINT chk_orders_status CHECK (status IN ('paid', 'confirmed', 'cancelled', 'draft'))
);

CREATE INDEX idx_orders_customer_id ON orders (customer_id);
CREATE INDEX idx_orders_salesperson_id ON orders (salesperson_id);
CREATE INDEX idx_orders_location_id ON orders (location_id);

CREATE TABLE order_items (
    id NUMBER(10) NOT NULL,
    order_id NUMBER(10) NOT NULL,
    product_variant_id NUMBER(10) NOT NULL,
    quantity NUMBER(10) NOT NULL,
    unit_price NUMBER(12,2) NOT NULL,
    icms_rate NUMBER(5,2) NOT NULL,
    ipi_rate NUMBER(5,2) NOT NULL,
    line_total NUMBER(12,2) NOT NULL,

    CONSTRAINT pk_order_items PRIMARY KEY (id),
    CONSTRAINT chk_order_items_quantity CHECK (quantity > 0)
);

CREATE INDEX idx_order_items_order_id ON order_items (order_id);
CREATE INDEX idx_order_items_product_variant_id ON order_items (product_variant_id);

ALTER TABLE employees
    ADD CONSTRAINT fk_employees_locations
    FOREIGN KEY (primary_location_id) REFERENCES locations(id);

ALTER TABLE addresses
    ADD CONSTRAINT fk_addresses_customers
    FOREIGN KEY (customer_id) REFERENCES customers(id);

ALTER TABLE orders
    ADD CONSTRAINT fk_orders_customers
    FOREIGN KEY (customer_id) REFERENCES customers(id);

ALTER TABLE orders
    ADD CONSTRAINT fk_orders_employees
    FOREIGN KEY (salesperson_id) REFERENCES employees(id);

ALTER TABLE orders
    ADD CONSTRAINT fk_orders_locations
    FOREIGN KEY (location_id) REFERENCES locations(id);

ALTER TABLE order_items
    ADD CONSTRAINT fk_order_items_orders
    FOREIGN KEY (order_id) REFERENCES orders(id);

ALTER TABLE order_items
    ADD CONSTRAINT fk_order_items_product_variants
    FOREIGN KEY (product_variant_id) REFERENCES product_variants(id);

-- Observação de performance Oracle:
-- FKs sem índice correspondente em colunas pai/filha podem provocar lock de tabela inteira
-- na operação de UPDATE/DELETE na tabela pai. Por isso, o índice em colunas de FK é obrigatório
-- em bases Oracle legadas e é parte da auditoria de lentidão e de integridade do schema.


-- Essa aqui identifica FK sem índice, o problema de lock
SELECT c.table_name, c.constraint_name, cc.column_name
FROM user_constraints c
JOIN user_cons_columns cc ON cc.constraint_name = c.constraint_name
WHERE c.constraint_type = 'R'
  AND NOT EXISTS (
      SELECT 1
      FROM user_ind_columns ic
      WHERE ic.table_name  = cc.table_name
        AND ic.column_name = cc.column_name
        AND ic.column_position = 1
  );