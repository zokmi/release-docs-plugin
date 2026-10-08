# Final fix fixture
PostgreSQL. Deploy selected full SQL files with psql --set ON_ERROR_STOP=1 --file <file>.
01_a.sql creates public.final_fix_a; 03_c.sql inserts id 7 and requires 01_a.sql.
02_b.sql creates independent public.final_fix_b; it is not selected in A+C.
Stop on any error, do not automatically rerun or rollback; preserve a tested backup first.
No application, ORM, migration tool or configuration exists in this fixture.
