[DbContext(typeof(AppDbContext))]
public class AppDbContextModelSnapshot : ModelSnapshot {
    protected override void BuildModel(ModelBuilder modelBuilder) {
        modelBuilder.Entity("Widgets", b => {
            b.Property<int>("Id");
            b.HasKey("Id");
            b.ToTable("Widgets");
        });
    }
}
