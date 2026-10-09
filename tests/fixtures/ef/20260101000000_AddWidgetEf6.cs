public partial class AddWidgetEf6 : DbMigration {
    public override void Up() {
        CreateTable("dbo.Widgets", c => new {
            Id = c.Int(nullable: false)
        }).PrimaryKey(t => t.Id);
    }
}
