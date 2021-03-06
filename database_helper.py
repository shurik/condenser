import os, uuid, csv
import config_reader
from pathlib import Path
from psycopg2.extras import execute_values, register_default_json, register_default_jsonb

register_default_json(loads=lambda x: x)
register_default_jsonb(loads=lambda x: x)

def copy_rows(source, destination, query, destination_table, destination_schema):
    cursor = source.cursor()
    cursor_name='table_cursor_'+str(uuid.uuid4()).replace('-','')
    q =f'DECLARE {cursor_name} SCROLL CURSOR FOR {query}'
    cursor.execute(q)

    fetch_row_count = 10000
    while True:
        cursor.execute(f'FETCH FORWARD {fetch_row_count} FROM {cursor_name}')
        if cursor.rowcount == 0:
            break

        destination_cursor = destination.cursor()

        execute_values(destination_cursor, f'INSERT INTO "{destination_schema}"."{destination_table}" VALUES %s', cursor.fetchall())

        destination_cursor.close()

    cursor.execute(f'CLOSE {cursor_name}')
    cursor.close()
    destination.commit()

def create_id_temp_table(conn, schema, col_type):
    table_name = 'temp_table_' + str(uuid.uuid4())
    cursor = conn.cursor()
    q = f'CREATE TABLE "{schema}"."{table_name}" (\n t    {col_type}\n)'
    cursor.execute(q)
    cursor.close()
    return table_name

def get_referencing_tables(table_name, tables, conn):
    return [r for r in get_fk_relationships(tables, conn) if r['child_table_name']==table_name]

def get_fk_relationships(tables, conn):
    cur = conn.cursor()

    q = """
    SELECT
        concat(concat(tc.table_schema, '.'),tc.table_name) as table_name,
        kcu.column_name as column_name,
        ccu.table_name AS underlying_table_name,
        ccu.column_name AS underlying_column_name
    FROM
        information_schema.table_constraints AS tc
        JOIN information_schema.key_column_usage AS kcu
            ON kcu.constraint_name = tc.constraint_name AND kcu.table_name = tc.table_name
        JOIN
                (SELECT
                    constraint_name,
                    concat(concat(min(table_schema),'.'),min(table_name)) AS table_name,
                    min(column_name) AS column_name
                FROM information_schema.constraint_column_usage
                GROUP BY
                    constraint_name
                ) AS ccu
            ON ccu.constraint_name = tc.constraint_name
    WHERE
    constraint_type='FOREIGN KEY'"""

    cur.execute(q)

    relationships = list()

    for row in cur.fetchall():
        d = dict()
        d['parent_table_name'] = row[0]
        d['fk_column_name'] = row[1]
        d['child_table_name'] = row[2]
        d['pk_column_name'] = row[3]

        if d['parent_table_name'] in tables and d['child_table_name'] in tables:
            relationships.append( d )

    cur.close()
    return relationships

def run_query(query, conn):
    cur = conn.cursor()
    cur.execute(query)
    cur.close()


def get_table_count(table_name, schema, conn):
    with conn.cursor() as cur:
        cur.execute(f'SELECT COUNT(*) FROM "{schema}"."{table_name}"')
        return cur.fetchone()[0]

def get_table_columns(table, schema, conn):
    with conn.cursor() as cur:
        cur.execute(f"SELECT column_name FROM information_schema.columns WHERE table_schema = '{schema}' AND table_name = '{table}'")
        return [r[0] for r in cur.fetchall()]

def list_all_user_schemas(conn):
    with conn.cursor() as cur:
        cur.execute("select nspname from pg_catalog.pg_namespace where nspname not like 'pg_%' and nspname != 'information_schema';")
        return [r[0] for r in cur.fetchall()]

def list_all_tables(conn):
    with conn.cursor() as cur:
        cur.execute(f"""SELECT
                            concat(concat(table_schema,'.'),table_name)
                        FROM
                            information_schema.tables
                        WHERE
                            table_schema NOT IN ('information_schema', 'pg_catalog');""")
        return [r[0] for r in cur.fetchall()]
