INSERT INTO currencies (code, name, is_fiat, unit_kind) VALUES
    ('CLP', 'Peso chileno',             TRUE,  'currency'),
    ('USD', 'Dólar estadounidense',     TRUE,  'currency'),
    ('EUR', 'Euro',                     TRUE,  'currency'),
    ('UF',  'Unidad de Fomento',        FALSE, 'index_unit'),
    ('UTM', 'Unidad Tributaria Mensual',FALSE, 'index_unit')
ON CONFLICT (code) DO NOTHING;
