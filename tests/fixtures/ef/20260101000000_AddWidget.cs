public partial class AddWidget : Migration {
    protected override void Up(MigrationBuilder migrationBuilder) {
        migrationBuilder.CreateTable(
            name: "Widgets",
            columns: table => new { Id = table.Column<int>(type: "int", nullable: false) },
            constraints: table => { table.PrimaryKey("PK_Widgets", x => x.Id); });
        migrationBuilder.CreateIndex(name: "IX_Widgets_Id", table: "Widgets", column: "Id");
    }
}
