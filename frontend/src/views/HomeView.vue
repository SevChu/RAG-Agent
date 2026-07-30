<template>
  <section class="welcome">
    <p class="eyebrow">DAY 1 · FOUNDATION</p>
    <h1>工程骨架已经就绪</h1>
    <p class="summary">
      前端与后端已经具备独立启动入口。课程空间、资料管理、学科问答等功能将在后续阶段逐步接入。
    </p>

    <div class="module-grid">
      <article>
        <span>01</span>
        <h2>课程空间</h2>
        <p>创建并管理相互隔离的课程。</p>
        <el-tag type="info" effect="plain">下一步实现</el-tag>
      </article>
      <article>
        <span>02</span>
        <h2>资料管理</h2>
        <p>上传课程资料并跟踪索引状态。</p>
        <el-tag type="info" effect="plain">等待实现</el-tag>
      </article>
      <article>
        <span>03</span>
        <h2>智能学习</h2>
        <p>提供带引用的问答、总结与出题。</p>
        <el-tag type="info" effect="plain">后续阶段</el-tag>
      </article>
    </div>
  </section>
</template>

<style scoped>
.welcome {
  padding: 44px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 24px;
  box-shadow: 0 20px 60px rgb(15 23 42 / 8%);
}

.eyebrow {
  margin: 0 0 12px;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.16em;
  color: #c2410c;
}

h1 {
  margin: 0;
  font-size: clamp(30px, 5vw, 48px);
  line-height: 1.12;
  color: #14213d;
}

.summary {
  max-width: 680px;
  margin: 20px 0 36px;
  font-size: 16px;
  line-height: 1.8;
  color: #475569;
}

.module-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}

article {
  padding: 22px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 16px;
}

article > span {
  font-size: 12px;
  font-weight: 800;
  color: #f59e0b;
}

h2 {
  margin: 10px 0 8px;
  font-size: 18px;
  color: #1e293b;
}

article p {
  min-height: 48px;
  margin: 0 0 18px;
  line-height: 1.6;
  color: #64748b;
}

@media (max-width: 760px) {
  .welcome {
    padding: 28px 22px;
  }

  .module-grid {
    grid-template-columns: 1fr;
  }

  article p {
    min-height: 0;
  }
}
</style>
