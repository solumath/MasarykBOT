from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from bot.db.tables import SUBJECTS
from bot.db.utils import Table, inject_conn, DBConnection, Record, Url, Entity



@dataclass
class CourseEntity(Entity):
    faculty: str
    code: str
    name: str
    url: Url
    terms: List[str]
    created_at: datetime
    edited_at: Optional[datetime]
    deleted_at: Optional[datetime]



class CourseRepository(Table):
    def __init__(self):
        super().__init__(table_name=SUBJECTS)

    @inject_conn
    async def autocomplete(self, conn: DBConnection, pattern: str) -> List[CourseEntity]:
        rows = await conn.fetch(f"""
            SELECT *
            FROM muni.courses
            WHERE lower(concat(faculty, ':', code, ' ', substr(name, 1, 50))) LIKE lower($1)
            LIMIT 25
        """, pattern)
        return [CourseEntity.convert(row) for row in rows]

    @inject_conn
    async def find_by_code(self, conn: DBConnection, faculty: str, code: str) -> Optional[CourseEntity]:
        row = await conn.fetchrow(f"""
            SELECT *
            FROM muni.courses
            WHERE lower(faculty)=lower($1) AND lower(code)=lower($2)
        """, faculty, code)
        return CourseEntity.convert(row) if row else None