<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import * as api from '@/api/training'
import { fetchCourses } from '@/api/courses'
import { toFriendlyApiError } from '@/api/client'
import type { Course } from '@/types/api'
import type {
  Dataset,
  DatasetRevision,
  Manifest,
  Review,
  ReviewStatus,
  ValidationReport,
} from '@/types/training'
import { reviewLabels, useRequestGate } from '@/utils/training'
const items = ref<Dataset[]>([]),
  selected = ref<Dataset | null>(null),
  versions = ref<DatasetRevision[]>([]),
  version = ref<DatasetRevision | null>(null),
  history = ref<Review[]>([])
const courses = ref<Course[]>([]),
  offset = ref(0),
  moreVersions = ref(false),
  moreReviews = ref(false),
  busy = ref(false),
  loading = ref(false),
  error = ref(''),
  notice = ref(''),
  name = ref('')
const gate = useRequestGate(),
  listGate = useRequestGate(),
  reviewGate = useRequestGate()
const manifest = reactive<Manifest>({
  schema_version: 1,
  target: 'reranker',
  source: '',
  license_id: '',
  license_notes: '',
  training_allowed: false,
  pii_status: 'pending',
  pii_notes: '',
  source_course_ids: [],
})
const inputMode = ref<'file' | 'paste'>('file'),
  file = ref<File | null>(null),
  pasted = ref(''),
  report = ref<ValidationReport | null>(null),
  reviewer = ref(''),
  note = ref('')
watch(
  [manifest, file, pasted, inputMode],
  () => {
    report.value = null
  },
  { deep: true, flush: 'sync' },
)
const actions = computed<Exclude<ReviewStatus, 'draft'>[]>(
  () =>
    (
      ({
        draft: ['pending_review'],
        pending_review: ['approved', 'rejected'],
        approved: ['revoked'],
        rejected: ['pending_review'],
        revoked: ['pending_review'],
      }) as Record<ReviewStatus, Exclude<ReviewStatus, 'draft'>[]>
    )[version.value?.status ?? 'draft'],
)
async function loadList(page = offset.value) {
  const ticket = listGate.next()
  loading.value = true
  try {
    const result = await api.datasets(page)
    if (listGate.current(ticket)) {
      items.value = result
      offset.value = page
    }
  } catch (e) {
    if (listGate.current(ticket)) error.value = toFriendlyApiError(e).message
  } finally {
    if (listGate.current(ticket)) loading.value = false
  }
}
async function showRevision(item: DatasetRevision, append = false) {
  const ticket = reviewGate.next()
  if (!append) {
    version.value = item
    history.value = []
  }
  try {
    const rows = await api.reviews(item.dataset_id, item.id, append ? history.value.length : 0)
    if (reviewGate.current(ticket)) {
      history.value = append ? [...history.value, ...rows] : rows
      moreReviews.value = rows.length === 20
    }
  } catch (e) {
    if (reviewGate.current(ticket)) error.value = toFriendlyApiError(e).message
  }
}
async function select(item: Dataset, keep?: string) {
  const ticket = gate.next()
  reviewGate.next()
  selected.value = item
  version.value = null
  versions.value = []
  history.value = []
  error.value = ''
  try {
    const [fresh, rows] = await Promise.all([api.dataset(item.id), api.revisions(item.id)])
    if (!gate.current(ticket)) return
    selected.value = fresh
    versions.value = rows
    moreVersions.value = rows.length === 20
    const first = rows.find((r) => r.id === keep) ?? rows[0]
    if (first) await showRevision(first)
  } catch (e) {
    if (gate.current(ticket)) error.value = toFriendlyApiError(e).message
  }
}
async function more() {
  if (!selected.value) return
  const ticket = gate.next()
  try {
    const rows = await api.revisions(selected.value.id, versions.value.length)
    if (gate.current(ticket)) {
      versions.value.push(...rows)
      moreVersions.value = rows.length === 20
    }
  } catch (e) {
    if (gate.current(ticket)) error.value = toFriendlyApiError(e).message
  }
}
async function action(work: () => Promise<void>) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    await work()
  } catch (e) {
    error.value = toFriendlyApiError(e).message + '（输入已保留；版本冲突时请刷新后重新复核。）'
  } finally {
    busy.value = false
  }
}
function selectedFile(): File {
  const result =
    inputMode.value === 'paste'
      ? new File([pasted.value], 'samples.jsonl', { type: 'application/jsonl' })
      : file.value
  if (!result || !result.size)
    throw { code: 'INVALID_INPUT', message: '请选择 JSONL 文件或粘贴样本。' }
  if (result.size > 8 * 1024 * 1024)
    throw { code: 'FILE_TOO_LARGE', message: '训练样本最多 8 MiB。' }
  return result
}
function pickFile(event: Event) {
  file.value = (event.target as HTMLInputElement).files?.[0] ?? null
}
async function create() {
  await action(async () => {
    const item = await api.createDataset(name.value.trim())
    await loadList(0)
    await select(item)
    name.value = ''
    notice.value = '数据集已创建，可以登记首个版本。'
  })
}
async function validate() {
  await action(async () => {
    report.value = await api.validate({ ...manifest }, selectedFile())
  })
}
async function upload() {
  const dataset = selected.value
  if (!dataset || !report.value?.valid) return
  await action(async () => {
    const saved = await api.upload(dataset.id, dataset.row_version, { ...manifest }, selectedFile())
    await select(dataset, saved.id)
    await loadList()
    notice.value = '新版本已登记，仍需审核后才能用于任务。'
  })
}
async function review(status: Exclude<ReviewStatus, 'draft'>) {
  const dataset = selected.value,
    item = version.value
  if (!dataset || !item) return
  await action(async () => {
    await api.review(
      dataset.id,
      item.id,
      dataset.row_version,
      status,
      reviewer.value.trim(),
      note.value.trim(),
    )
    await select(dataset, item.id)
    notice.value = '审核记录已保存。'
    await loadList()
  })
}
onMounted(() => {
  void loadList()
  void fetchCourses()
    .then((rows) => {
      courses.value = rows
    })
    .catch((e) => {
      error.value = toFriendlyApiError(e).message
    })
})
</script>
<template>
  <p v-if="error" class="training-error" role="alert">{{ error }}</p>
  <p v-if="notice" class="training-note" role="status">{{ notice }}</p>
  <div class="training-split">
    <aside>
      <section class="training-card">
        <h2>训练数据</h2>
        <form @submit.prevent="create">
          <label
            >新数据集名称<input
              v-model="name"
              maxlength="100"
              required
              :disabled="busy"
              placeholder="例如：重排序合成样本"
          /></label>
          <div class="training-actions">
            <button class="primary" :disabled="busy || !name.trim()">创建数据集</button>
          </div>
        </form>
        <hr />
        <p v-if="loading" role="status">正在加载…</p>
        <p v-if="!loading && !items.length" class="training-empty">
          还没有数据集。先创建一个，再登记样本版本。
        </p>
        <div class="training-list">
          <button
            v-for="item in items"
            :key="item.id"
            :class="{ selected: selected?.id === item.id }"
            :disabled="busy"
            @click="select(item)"
          >
            {{ item.name }}<br /><small>数据集 · {{ item.id.slice(0, 8) }}</small>
          </button>
        </div>
        <div class="training-actions">
          <button :disabled="busy || loading || offset === 0" @click="loadList(offset - 20)">
            上一页</button
          ><button :disabled="busy || loading || items.length < 20" @click="loadList(offset + 20)">
            下一页</button
          ><button :disabled="busy || loading" @click="loadList()">刷新列表</button>
        </div>
      </section>
    </aside>
    <div v-if="selected">
      <section class="training-card">
        <div class="training-section-title">
          <h2>{{ selected.name }}</h2>
          <button :disabled="busy" @click="select(selected, version?.id)">刷新版本</button>
        </div>
        <p class="training-muted">版本内容不可覆盖。修改样本或许可后，请登记新版本并重新审核。</p>
        <div class="training-list">
          <button
            v-for="item in versions"
            :key="item.id"
            :class="{ selected: version?.id === item.id }"
            :disabled="busy"
            @click="showRevision(item)"
          >
            版本 {{ item.revision_number }} · {{ reviewLabels[item.status] }} ·
            {{ item.report.sample_count }} 条 · {{ item.manifest.target }}
          </button>
        </div>
        <button v-if="moreVersions" :disabled="busy" @click="more">更多版本</button>
        <p v-if="!versions.length" class="training-empty">暂无版本，请在下方登记训练样本。</p>
        <div v-if="version">
          <h3>
            版本 {{ version.revision_number }}
            <span class="training-status" :class="version.status">{{
              reviewLabels[version.status]
            }}</span>
          </h3>
          <dl class="training-facts">
            <dt>来源</dt>
            <dd>{{ version.manifest.source }}</dd>
            <dt>许可</dt>
            <dd>{{ version.manifest.license_id }} · {{ version.manifest.license_notes }}</dd>
            <dt>隐私处理</dt>
            <dd>{{ version.manifest.pii_status }} · {{ version.manifest.pii_notes }}</dd>
            <dt>训练 / 验证样本</dt>
            <dd>
              {{ version.report.splits.train?.count ?? 0 }} /
              {{ version.report.splits.validation?.count ?? 0 }}
            </dd>
            <dt>登记校验</dt>
            <dd>
              {{ version.report.approvable ? '满足基础审核条件' : '存在待处理问题' }} ·
              {{ version.report.issue_count }} 项问题
            </dd>
            <dt>内容 SHA-256</dt>
            <dd>{{ version.report.content_sha256 }}</dd>
            <dt>去重方法</dt>
            <dd>标准化精确匹配 + 字符 5-gram Jaccard 近重复检查（0.85）</dd>
          </dl>
          <ul v-if="version.report.issues.length">
            <li v-for="(issue, index) in version.report.issues" :key="index">
              第 {{ issue.line ?? '—' }} 行：{{ issue.code }}
            </li>
          </ul>
          <h3>审核与撤销</h3>
          <p class="training-muted">
            请人工核对来源、许可和隐私。基础扫描不能替代审核；撤销会取消关联待执行任务。
          </p>
          <fieldset :disabled="busy">
            <div class="training-fields">
              <label
                >审核人<input v-model="reviewer" maxlength="200" placeholder="填写审核人" /></label
              ><label
                >审核说明<textarea
                  v-model="note"
                  maxlength="2000"
                  rows="2"
                  placeholder="记录核对依据或撤销原因"
                />
              </label>
            </div>
            <div class="training-actions">
              <button
                v-for="status in actions"
                :key="status"
                :disabled="
                  !reviewer.trim() ||
                  !note.trim() ||
                  (status === 'approved' && !version.report.approvable)
                "
                @click="review(status)"
              >
                {{
                  {
                    pending_review: '提交审核',
                    approved: '批准此版本',
                    rejected: '拒绝此版本',
                    revoked: '撤销审核',
                  }[status]
                }}
              </button>
            </div>
          </fieldset>
          <details>
            <summary>审核历史（{{ history.length }} 条已加载）</summary>
            <ol class="training-review-log">
              <li v-for="item in history" :key="item.id">
                #{{ item.sequence }} · {{ reviewLabels[item.status] }} · {{ item.reviewer }}
                <p>{{ item.note }}</p>
                <small>{{ new Date(item.created_at).toLocaleString() }}</small>
              </li>
            </ol>
            <button v-if="moreReviews" :disabled="busy" @click="showRevision(version, true)">
              更多审核记录
            </button>
          </details>
        </div>
      </section>
      <section class="training-card">
        <h2>登记新版本</h2>
        <p class="training-note">
          只接受 train / validation。test、封存测试集及来源不明数据不能用于训练。
        </p>
        <fieldset :disabled="busy">
          <div class="training-fields">
            <label
              >训练目标<select aria-label="训练目标" v-model="manifest.target">
                <option value="reranker">Reranker · 重排序</option>
                <option value="scorer">Scorer · 评分</option>
              </select></label
            ><label
              >来源说明<input
                v-model="manifest.source"
                maxlength="1000"
                placeholder="数据由谁创建，来自哪里" /></label
            ><label
              >许可标识<input
                v-model="manifest.license_id"
                maxlength="200"
                placeholder="例如 synthetic-owned" /></label
            ><label>许可及用途说明<input v-model="manifest.license_notes" maxlength="1000" /></label
            ><label
              >隐私状态<select aria-label="隐私状态" v-model="manifest.pii_status">
                <option value="pending">待处理</option>
                <option value="clean">已核对，无个人信息</option>
                <option value="redacted">已脱敏</option>
              </select></label
            ><label>隐私复核说明<input v-model="manifest.pii_notes" maxlength="1000" /></label
            ><label class="training-wide"
              >来源资料空间（独立合成数据可不选）<select
                v-model="manifest.source_course_ids"
                multiple
                aria-label="来源资料空间"
              >
                <option v-for="course in courses" :key="course.id" :value="course.id">
                  {{ course.name }}
                </option>
              </select></label
            ><label class="check-label training-wide"
              ><input
                v-model="manifest.training_allowed"
                type="checkbox"
              />确认来源许可允许训练</label
            ><label
              >样本输入方式<select aria-label="样本输入方式" v-model="inputMode">
                <option value="file">上传 JSONL 文件</option>
                <option value="paste">粘贴 JSONL</option>
              </select></label
            ><label v-if="inputMode === 'file'"
              >样本 JSONL 文件<input type="file" accept=".jsonl" @change="pickFile" /></label
            ><label v-else class="training-wide"
              >样本 JSONL<textarea
                v-model="pasted"
                rows="6"
                spellcheck="false"
                placeholder="每行一个 JSON 对象"
              />
            </label>
          </div>
          <details>
            <summary>查看样本字段要求</summary>
            <p class="training-muted">
              共同字段：id、source_id、group_id、split、query。Reranker 还需 document 与
              relevance（整数 0/1）；Scorer 还需
              response、evidence（非空字符串数组）、score（0～1）。train 与 validation
              都必须存在，来源分组不能跨 split。
            </p>
          </details>
          <div class="training-actions">
            <button @click="validate">校验样本</button
            ><button class="primary" :disabled="!report?.valid" @click="upload">登记新版本</button>
          </div>
        </fieldset>
        <div v-if="report" class="training-note" role="status">
          <strong>{{ report.valid ? '格式校验通过' : '格式校验未通过' }}</strong> ·
          {{ report.sample_count }} 条；{{
            report.approvable ? '满足基础审核条件' : '需先处理审核问题'
          }}
          <ul>
            <li v-for="(issue, index) in report.issues" :key="index">
              第 {{ issue.line ?? '—' }} 行：{{ issue.code
              }}<template v-if="issue.related_line"
                >（关联第 {{ issue.related_line }} 行）</template
              >
            </li>
          </ul>
          <span v-if="report.issue_count > report.issues.length"
            >共 {{ report.issue_count }} 项，仅展示部分。</span
          >
        </div>
      </section>
    </div>
    <section v-else class="training-card training-empty">
      <h2>从一个明确的数据版本开始</h2>
      <p>在左侧创建或选择数据集，登记样本、查看校验结果并完成审核。</p>
    </section>
  </div>
</template>
